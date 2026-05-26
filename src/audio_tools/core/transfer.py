"""Transfer orchestration: transcode -> sha1-skip copy -> m3u write -> session row."""
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePath
from typing import Callable, Optional

from sqlalchemy.orm import Session

from audio_tools.core import album_art as album_art_mod
from audio_tools.core.hashing import sha1_of
from audio_tools.core.models import DeviceProfile, Track, TransferSession
from audio_tools.core.transcoder import (
    FfmpegRunner,
    TranscodeItem,
    batch_transcode,
)
from audio_tools.core.transfer_planner import TransferPlan
from audio_tools.core.transfer_target import TransferTarget


CODEC_EXTENSIONS = {"opus": ".opus", "mp3": ".mp3", "aac": ".m4a", "copy": ""}


@dataclass
class TransferOutcome:
    session_id: int
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _ext_for_codec(codec: str, source_path: Path) -> str:
    if codec == "copy":
        return source_path.suffix
    return CODEC_EXTENSIONS[codec]


def _build_relpath(profile: DeviceProfile, track: Track, codec: str) -> PurePath:
    fields = {
        "artist": (track.artist or "Unknown Artist"),
        "album": (track.album or "Unknown Album"),
        "title": (track.title or Path(track.path).stem),
        "track": 0,
    }
    layout = profile.folder_layout.format(**fields)
    safe_parts = []
    for part in PurePath(layout).parts:
        safe_parts.append(part.replace("/", "_").replace("\\", "_"))
    safe = PurePath(*safe_parts)
    return safe.with_suffix(_ext_for_codec(codec, Path(track.path)))


def _format_m3u(
    profile: DeviceProfile,
    items: list[tuple[Track, PurePath]],
) -> str:
    from audio_tools.core import m3u_path_style as styles

    lines = ["#EXTM3U"]
    for track, relpath in items:
        duration = int(track.duration_s) if track.duration_s is not None else -1
        artist = track.artist or ""
        title = track.title or Path(track.path).stem
        lines.append(f"#EXTINF:{duration},{artist} - {title}")
        lines.append(styles.format_path(relpath, profile.m3u_path_style))
    lines.append("")
    return "\n".join(lines)


def execute_transfer(
    *,
    session: Session,
    profile: DeviceProfile,
    plan: TransferPlan,
    target: TransferTarget,
    ffmpeg: FfmpegRunner,
    m3u_relpath: PurePath,
    cache_dir: Path,
    workers: int = 1,
    keep_temp: bool = False,
) -> TransferOutcome:
    cache_dir.mkdir(parents=True, exist_ok=True)

    ts = TransferSession(
        profile_id=profile.id,
        started_at=datetime.utcnow(),
        status="running",
        bytes_transferred=0,
        bitrate_kbps=plan.bitrate_kbps if plan.bitrate_kbps else None,
        kept_count=len(plan.kept),
        dropped_count=len(plan.dropped),
    )
    session.add(ts); session.commit()
    outcome = TransferOutcome(session_id=ts.id)

    relpaths: dict[int, PurePath] = {}
    items: list[TranscodeItem] = []
    track_lookup: dict[int, Track] = {}
    for planned in plan.kept:
        track = session.get(Track, planned.track_id)
        if track is None:
            outcome.failed += 1
            outcome.errors.append(f"track id={planned.track_id} not found")
            continue
        track_lookup[track.id] = track
        relpath = _build_relpath(profile, track, planned.codec)
        relpaths[track.id] = relpath
        ext = _ext_for_codec(planned.codec, Path(track.path))
        staged = cache_dir / f"{track.id}{ext}"
        items.append(TranscodeItem(
            track_id=track.id,
            src=Path(track.path),
            dst=staged,
            codec=planned.codec,
            bitrate_kbps=planned.bitrate_kbps,
            sample_rate_max=profile.sample_rate_max,
        ))

    successful_tracks: list[Track] = []
    for r in batch_transcode(ffmpeg, items, workers=workers):
        track = track_lookup[r.track_id]
        if not r.ok:
            outcome.failed += 1
            outcome.errors.append(f"{track.path}: {r.error}")
            continue

        item = next(i for i in items if i.track_id == r.track_id)
        try:
            album_art_mod.preserve_album_art(item.src, item.dst, item.codec)
        except Exception as e:
            outcome.errors.append(f"art preserve {track.path}: {e}")

        relpath = relpaths[track.id]
        staged_sha1 = sha1_of(item.dst)
        if target.exists(relpath) and target.file_sha1(relpath) == staged_sha1:
            outcome.skipped += 1
        else:
            target.copy_file(item.dst, relpath)
            ts.bytes_transferred += item.dst.stat().st_size
            outcome.copied += 1
        successful_tracks.append(track)

    if successful_tracks:
        m3u_text = _format_m3u(profile, [(t, relpaths[t.id]) for t in successful_tracks])
        target.write_text(m3u_relpath, m3u_text)

    total_attempted = outcome.copied + outcome.skipped + outcome.failed
    if total_attempted and outcome.failed / total_attempted > 0.5:
        ts.status = "failed"
        ts.error = "; ".join(outcome.errors[:5])
    else:
        ts.status = "completed"
    ts.finished_at = datetime.utcnow()
    session.commit()

    if not keep_temp:
        shutil.rmtree(cache_dir, ignore_errors=True)

    return outcome
