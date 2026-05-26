import shutil
import subprocess
from pathlib import Path

import pytest

from audio_tools.core.transcoder import RealFfmpegRunner, transcode

FIXTURE = Path(__file__).parent.parent / "fixtures" / "audio" / "test_tagged.mp3"

ffmpeg_available = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg not on PATH")


def _ensure_fixture():
    if not FIXTURE.exists():
        subprocess.run(
            ["bash", str(FIXTURE.parent.parent / "generate_audio_fixtures.sh")],
            check=True,
        )


@pytest.mark.parametrize("codec,ext", [("opus", ".opus"), ("mp3", ".mp3"), ("aac", ".m4a")])
def test_real_ffmpeg_produces_playable_output(tmp_path, codec, ext):
    _ensure_fixture()
    runner = RealFfmpegRunner()
    dst = tmp_path / f"out{ext}"
    transcode(runner, FIXTURE, dst, codec=codec, bitrate_kbps=96, sample_rate_max=48000)
    assert dst.exists() and dst.stat().st_size > 0

    import mutagen
    mf = mutagen.File(dst)
    assert mf is not None, f"mutagen could not read {dst}"
    if codec == "opus":
        assert "OggOpus" in type(mf).__name__
    elif codec == "mp3":
        assert "MP3" in type(mf).__name__
    elif codec == "aac":
        assert "MP4" in type(mf).__name__
