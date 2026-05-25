from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.core import tags
from audio_tools.core.models import Track

SUPPORTED_EXTENSIONS = frozenset({".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"})


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    moved: int = 0
    skipped: int = 0


def discover_audio_files(root: Path) -> Iterator[Path]:
    """Yield absolute paths of all supported audio files under root (recursive)."""
    root = root.resolve()
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def scan(root: Path, session: Session) -> ScanResult:
    """Walk root and reconcile with the tracks table.

    - New file → INSERT
    - Existing file with changed mtime → UPDATE metadata
    - Existing tracked path no longer on disk → DELETE
    """
    result = ScanResult()

    existing: dict[str, Track] = {
        t.path: t for t in session.scalars(select(Track)).all()
    }
    seen_paths: set[str] = set()

    for file_path in discover_audio_files(root):
        path_str = str(file_path)
        seen_paths.add(path_str)
        stat = file_path.stat()

        existing_track = existing.get(path_str)
        if existing_track is None:
            try:
                meta = tags.read_tags(file_path)
            except tags.UnsupportedAudioError:
                result.skipped += 1
                continue
            session.add(Track(
                path=path_str,
                mtime=stat.st_mtime,
                size=stat.st_size,
                sha1=None,
                title=meta.get("title"),
                artist=meta.get("artist"),
                album=meta.get("album"),
                duration_s=meta.get("duration_s"),
                codec=meta.get("codec"),
                bitrate=meta.get("bitrate"),
            ))
            result.added += 1
        elif existing_track.mtime != stat.st_mtime or existing_track.size != stat.st_size:
            try:
                meta = tags.read_tags(file_path)
            except tags.UnsupportedAudioError:
                result.skipped += 1
                continue
            existing_track.mtime = stat.st_mtime
            existing_track.size = stat.st_size
            existing_track.sha1 = None  # invalidate; will be recomputed in task 9
            existing_track.title = meta.get("title")
            existing_track.artist = meta.get("artist")
            existing_track.album = meta.get("album")
            existing_track.duration_s = meta.get("duration_s")
            existing_track.codec = meta.get("codec")
            existing_track.bitrate = meta.get("bitrate")
            result.updated += 1

    # Removals: tracks whose path was not seen this scan
    for path, track in existing.items():
        if path not in seen_paths:
            session.delete(track)
            result.removed += 1

    session.commit()
    return result
