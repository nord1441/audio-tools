from datetime import datetime
from pathlib import Path, PurePath

import pytest
from sqlalchemy import select

from audio_tools.core.models import (
    DeviceProfile,
    Track,
    TransferSession,
)
from audio_tools.core.transcoder import FakeFfmpegRunner
from audio_tools.core.transfer import TransferOutcome, execute_transfer
from audio_tools.core.transfer_planner import (
    PlannedTrack,
    TransferPlan,
)
from audio_tools.core.transfer_target import LocalDirectoryTarget


def _profile(session, **kwargs) -> DeviceProfile:
    defaults = dict(
        name="dev", codec="opus", container="ogg",
        max_bitrate=128, min_bitrate=64, bitrate_step=32,
        max_size_bytes=1_000_000_000, sample_rate_max=48000,
        m3u_path_style="relative",
        folder_layout="{artist}/{title}",
    )
    defaults.update(kwargs)
    p = DeviceProfile(**defaults)
    session.add(p); session.flush()
    return p


def _track(session, **kwargs) -> Track:
    defaults = dict(path="/m/song.mp3", mtime=0.0, size=1000,
                    title="Song", artist="Artist", duration_s=180.0)
    defaults.update(kwargs)
    t = Track(**defaults)
    session.add(t); session.flush()
    return t


def _plan_from(tracks: list[Track], codec="opus", bitrate=96) -> TransferPlan:
    kept = [
        PlannedTrack(
            track_id=t.id, source_path=Path(t.path),
            output_size_bytes=t.size, codec=codec, bitrate_kbps=bitrate,
        )
        for t in tracks
    ]
    return TransferPlan(
        bitrate_kbps=bitrate, kept=kept, dropped=[],
        total_kept_bytes=sum(t.size for t in tracks),
    )


def test_execute_transfer_happy_path(tmp_path, session):
    src = tmp_path / "song.mp3"; src.write_bytes(b"audio bytes")
    track = _track(session, path=str(src))
    profile = _profile(session)
    target_root = tmp_path / "device"; target_root.mkdir()
    target = LocalDirectoryTarget(target_root)
    runner = FakeFfmpegRunner()

    out = execute_transfer(
        session=session,
        profile=profile,
        plan=_plan_from([track]),
        target=target,
        ffmpeg=runner,
        m3u_relpath=PurePath("Playlists/all.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert isinstance(out, TransferOutcome)
    assert out.copied == 1 and out.skipped == 0 and out.failed == 0

    assert (target_root / "Artist" / "Song.opus").exists()

    rows = session.scalars(select(TransferSession)).all()
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].kept_count == 1
    assert rows[0].dropped_count == 0
    assert rows[0].finished_at is not None
    assert rows[0].bytes_transferred > 0

    m3u_text = (target_root / "Playlists/all.m3u").read_text()
    assert "Artist/Song.opus" in m3u_text


def test_execute_transfer_skips_existing_sha1_match(tmp_path, session):
    src = tmp_path / "song.mp3"; src.write_bytes(b"audio bytes")
    track = _track(session, path=str(src))
    profile = _profile(session)
    target_root = tmp_path / "device"; target_root.mkdir()
    target = LocalDirectoryTarget(target_root)
    runner = FakeFfmpegRunner()

    out1 = execute_transfer(
        session=session, profile=profile, plan=_plan_from([track]),
        target=target, ffmpeg=runner,
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert out1.copied == 1

    out2 = execute_transfer(
        session=session, profile=profile, plan=_plan_from([track]),
        target=target, ffmpeg=runner,
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache2",
    )
    assert out2.skipped == 1 and out2.copied == 0


def test_execute_transfer_failed_track_continues(tmp_path, session):
    from subprocess import CompletedProcess

    src_a = tmp_path / "a.mp3"; src_a.write_bytes(b"good")
    src_b = tmp_path / "b.mp3"; src_b.write_bytes(b"bad")
    tracks = [_track(session, path=str(src_a), title="A"),
              _track(session, path=str(src_b), title="B")]
    profile = _profile(session)
    target_root = tmp_path / "device"; target_root.mkdir()
    target = LocalDirectoryTarget(target_root)

    class BRunner:
        def run(self, args):
            if "b.mp3" in " ".join(args):
                return CompletedProcess(args, returncode=1, stdout=b"", stderr=b"bad")
            import shutil
            i_idx = args.index("-i")
            shutil.copyfile(args[i_idx + 1], args[-1])
            return CompletedProcess(args, returncode=0, stdout=b"", stderr=b"")

    out = execute_transfer(
        session=session, profile=profile, plan=_plan_from(tracks),
        target=target, ffmpeg=BRunner(),
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert out.copied == 1 and out.failed == 1
    row = session.scalars(select(TransferSession)).first()
    assert row.status == "completed"


def test_execute_transfer_majority_failed_marks_failed(tmp_path, session):
    from subprocess import CompletedProcess

    tracks = []
    for i in range(4):
        src = tmp_path / f"t{i}.mp3"; src.write_bytes(b"x")
        tracks.append(_track(session, path=str(src), title=f"T{i}"))

    class AllBadRunner:
        def run(self, args):
            return CompletedProcess(args, returncode=1, stdout=b"", stderr=b"boom")

    target_root = tmp_path / "device"; target_root.mkdir()
    out = execute_transfer(
        session=session, profile=_profile(session),
        plan=_plan_from(tracks),
        target=LocalDirectoryTarget(target_root),
        ffmpeg=AllBadRunner(),
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert out.failed == 4
    row = session.scalars(select(TransferSession)).first()
    assert row.status == "failed"
