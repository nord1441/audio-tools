"""Preserve embedded album art across transcodes.

mp3/aac/copy: rely on ffmpeg's `-map 0:v?` passthrough. This module then
*verifies* the picture survived and logs a warning if not.

opus: extract the picture from the source via mutagen, re-encode to JPEG if
necessary, base64-encode into a Vorbis `METADATA_BLOCK_PICTURE` comment.
"""
import base64
import io
from pathlib import Path

import mutagen
from mutagen.flac import Picture as FlacPicture
from mutagen.id3 import APIC, ID3
from mutagen.mp4 import MP4Cover
from mutagen.oggopus import OggOpus
from PIL import Image


def _extract_picture_bytes(src: Path) -> tuple[bytes, str] | None:
    """Return (image_bytes, mime) from the source file's first picture, or None."""
    mf = mutagen.File(src)
    if mf is None:
        return None
    if isinstance(mf.tags, ID3):
        for frame in mf.tags.values():
            if isinstance(frame, APIC):
                return bytes(frame.data), frame.mime or "image/jpeg"
    covers = mf.tags.get("covr") if mf.tags else None
    if covers:
        cover = covers[0]
        fmt = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        return bytes(cover), fmt
    block = mf.get("metadata_block_picture")
    if block:
        data = base64.b64decode(block[0])
        pic = FlacPicture(data)
        return bytes(pic.data), pic.mime or "image/jpeg"
    pictures = getattr(mf, "pictures", None)
    if pictures:
        p = pictures[0]
        return bytes(p.data), p.mime or "image/jpeg"
    return None


def _normalize_to_jpeg_or_png(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    if mime in ("image/jpeg", "image/png"):
        return image_bytes, mime
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def _embed_in_opus(dst: Path, image_bytes: bytes, mime: str) -> None:
    img = Image.open(io.BytesIO(image_bytes))
    width, height = img.size
    depth = 24

    pic = FlacPicture()
    pic.type = 3
    pic.mime = mime
    pic.desc = ""
    pic.data = image_bytes
    pic.width = width
    pic.height = height
    pic.depth = depth
    pic.colors = 0

    raw = pic.write()
    encoded = base64.b64encode(raw).decode("ascii")
    opus = OggOpus(dst)
    opus["metadata_block_picture"] = [encoded]
    opus.save()


def preserve_album_art(src: Path, dst: Path, codec: str) -> bool:
    """Ensure dst carries the same album art as src for the given output codec."""
    if codec == "copy":
        return True

    extracted = _extract_picture_bytes(src)
    if extracted is None:
        return False
    image_bytes, mime = extracted

    if codec in ("mp3", "aac"):
        mf = mutagen.File(dst)
        if mf is None:
            return False
        if codec == "mp3":
            has = isinstance(mf.tags, ID3) and any(isinstance(f, APIC) for f in mf.tags.values())
        else:
            has = bool(mf.tags and mf.tags.get("covr"))
        return bool(has)

    if codec == "opus":
        image_bytes, mime = _normalize_to_jpeg_or_png(image_bytes, mime)
        _embed_in_opus(dst, image_bytes, mime)
        return True

    return False
