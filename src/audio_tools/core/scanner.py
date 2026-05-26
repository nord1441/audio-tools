from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.core import tags
from audio_tools.core.hashing import sha1_of
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
    root = root.resolve()
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def _read_meta_and_size(file_path: Path) -> Optional[dict]:
    """Returns dict suitable for splatting into Track(), or None if file unreadable."""
    try:
        meta = tags.read_tags(file_path)
    except tags.UnsupportedAudioError:
        return None
    stat = file_path.stat()
    return {
        "path": str(file_path),
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "sha1": sha1_of(file_path),
        "title": meta.get("title"),
        "artist": meta.get("artist"),
        "album": meta.get("album"),
        "duration_s": meta.get("duration_s"),
        "codec": meta.get("codec"),
        "bitrate": meta.get("bitrate"),
    }


def scan(root: Path, session: Session) -> ScanResult:
    """Walk root and reconcile with the tracks table.

    Sequence:
      1. Build map of {path -> Track} for everything currently in DB.
      2. Walk filesystem; classify each file as new/unchanged/modified.
      3. For paths missing on disk, look for a sha1 match among new files -> MOVE.
      4. Remaining missing -> DELETE. Remaining new -> INSERT.
    """
    result = ScanResult()
    existing: dict[str, Track] = {
        t.path: t for t in session.scalars(select(Track)).all()
    }
    seen_paths: set[str] = set()
    new_candidates: dict[str, dict] = {}  # path -> meta dict

    for file_path in discover_audio_files(root):
        path_str = str(file_path)
        seen_paths.add(path_str)
        stat = file_path.stat()

        existing_track = existing.get(path_str)
        if existing_track is None:
            meta = _read_meta_and_size(file_path)
            if meta is None:
                result.skipped += 1
                continue
            new_candidates[path_str] = meta
        elif existing_track.mtime != stat.st_mtime or existing_track.size != stat.st_size:
            meta = _read_meta_and_size(file_path)
            if meta is None:
                result.skipped += 1
                continue
            existing_track.mtime = meta["mtime"]
            existing_track.size = meta["size"]
            existing_track.sha1 = meta["sha1"]
            existing_track.title = meta["title"]
            existing_track.artist = meta["artist"]
            existing_track.album = meta["album"]
            existing_track.duration_s = meta["duration_s"]
            existing_track.codec = meta["codec"]
            existing_track.bitrate = meta["bitrate"]
            result.updated += 1
        # else: unchanged — no DB write

    # Reconcile missing paths against new candidates via sha1 (move detection)
    missing_tracks = [t for path, t in existing.items() if path not in seen_paths]
    sha1_to_candidate = {m["sha1"]: path for path, m in new_candidates.items()}

    for track in missing_tracks:
        if track.sha1 and track.sha1 in sha1_to_candidate:
            new_path = sha1_to_candidate.pop(track.sha1)
            meta = new_candidates.pop(new_path)
            track.path = new_path
            track.mtime = meta["mtime"]
            track.size = meta["size"]
            # sha1 is unchanged by definition
            result.moved += 1
        else:
            session.delete(track)
            result.removed += 1

    # Remaining new candidates are genuine inserts
    for meta in new_candidates.values():
        session.add(Track(**meta))
        result.added += 1

    session.commit()
    return result
