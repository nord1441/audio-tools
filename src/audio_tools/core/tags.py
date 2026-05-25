from pathlib import Path
from typing import Any, Optional, TypedDict

import mutagen
from mutagen import MutagenError


class TagDict(TypedDict, total=False):
    title: Optional[str]
    artist: Optional[str]
    album: Optional[str]
    duration_s: Optional[float]
    codec: Optional[str]
    bitrate: Optional[int]


class UnsupportedAudioError(Exception):
    """Raised when a file is not a recognized audio format."""


_CODEC_MAP = {
    "MP3": "mp3",
    "FLAC": "flac",
    "MP4": "aac",
    "OggOpus": "opus",
    "OggVorbis": "vorbis",
    "WavPack": "wavpack",
    "WAVE": "wav",
}


def _first(value: Any) -> Optional[str]:
    """mutagen returns lists for many tag values; flatten to first string.

    Handles three shapes mutagen produces:
    - None              → None
    - list (EasyID3)    → first element as str, or None if empty
    - TextFrame (ID3)   → first element of .text list as str
    - other             → str(value)
    """
    if value is None:
        return None
    # Raw ID3 TextFrame objects expose a .text list attribute
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value)


def read_tags(path: Path) -> TagDict:
    try:
        mf = mutagen.File(path)
    except MutagenError as e:
        raise UnsupportedAudioError(f"mutagen could not read {path}: {e}") from e
    if mf is None:
        raise UnsupportedAudioError(f"Unrecognized audio format: {path}")

    info = mf.info
    tag_class_name = type(mf).__name__
    codec = _CODEC_MAP.get(tag_class_name, tag_class_name.lower())

    bitrate_bps: Optional[int] = getattr(info, "bitrate", None)
    bitrate_kbps = int(bitrate_bps / 1000) if bitrate_bps is not None else None

    return TagDict(
        title=_first(mf.get("title") or mf.get("TIT2")),
        artist=_first(mf.get("artist") or mf.get("TPE1")),
        album=_first(mf.get("album") or mf.get("TALB")),
        duration_s=float(info.length) if getattr(info, "length", None) else None,
        codec=codec,
        bitrate=bitrate_kbps,
    )
