from pathlib import Path
from typing import Iterator

SUPPORTED_EXTENSIONS = frozenset({".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav"})


def discover_audio_files(root: Path) -> Iterator[Path]:
    """Yield absolute paths of all supported audio files under root (recursive)."""
    root = root.resolve()
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path
