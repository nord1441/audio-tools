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
    """Walk root and reconcile new files with the tracks table.

    Phase 1 scope: detect new files only. Updates/removes/moves arrive in tasks 8-9.
    """
    result = ScanResult()
    known_paths = set(session.scalars(select(Track.path)).all())

    for file_path in discover_audio_files(root):
        path_str = str(file_path)
        if path_str in known_paths:
            continue
        try:
            meta = tags.read_tags(file_path)
        except tags.UnsupportedAudioError:
            result.skipped += 1
            continue

        stat = file_path.stat()
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

    session.commit()
    return result
