import shutil
import subprocess
from pathlib import Path

import pytest

ffmpeg = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(ffmpeg is None, reason="ffmpeg not on PATH")


FIXTURES = Path(__file__).parent.parent / "fixtures" / "audio"


@pytest.fixture(scope="session")
def tagged_mp3_with_art(tmp_path_factory):
    """Generate a small mp3 with an embedded JPEG cover."""
    work = tmp_path_factory.mktemp("art_fixture")
    cover = work / "cover.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=red:s=2x2:d=1",
         "-frames:v", "1", str(cover)],
        check=True,
    )
    audio = work / "in.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-i", str(cover),
         "-map", "0:a", "-map", "1:v",
         "-c:a", "libmp3lame", "-b:a", "128k",
         "-c:v", "copy",
         "-id3v2_version", "3",
         str(audio)],
        check=True,
    )
    return audio


def _has_picture(path: Path, codec: str) -> bool:
    import mutagen
    mf = mutagen.File(path)
    if mf is None:
        return False
    if codec == "mp3":
        from mutagen.id3 import APIC
        return any(isinstance(f, APIC) for f in mf.tags.values()) if mf.tags else False
    if codec == "aac":
        return bool(mf.tags.get("covr")) if mf.tags else False
    if codec == "opus":
        return bool(mf.get("metadata_block_picture"))
    return False


@pytest.mark.parametrize("codec,ext", [("mp3", ".mp3"), ("aac", ".m4a"), ("opus", ".opus")])
def test_album_art_preserved(tmp_path, tagged_mp3_with_art, codec, ext):
    from audio_tools.core.album_art import preserve_album_art
    from audio_tools.core.transcoder import RealFfmpegRunner, transcode

    dst = tmp_path / f"out{ext}"
    transcode(RealFfmpegRunner(), tagged_mp3_with_art, dst,
              codec=codec, bitrate_kbps=96, sample_rate_max=48000)

    preserved = preserve_album_art(tagged_mp3_with_art, dst, codec)
    if codec == "opus":
        assert preserved is True
    assert _has_picture(dst, codec), f"no picture in {dst}"
