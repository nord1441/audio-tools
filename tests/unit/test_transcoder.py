from pathlib import Path
from subprocess import CompletedProcess

import pytest

from audio_tools.core.transcoder import (
    FakeFfmpegRunner,
    TranscodeError,
    transcode,
)


def test_fake_runner_records_args(tmp_path):
    runner = FakeFfmpegRunner()
    src = tmp_path / "a.mp3"; src.write_bytes(b"audio")
    dst = tmp_path / "out.opus"
    transcode(runner, src, dst, codec="opus", bitrate_kbps=128, sample_rate_max=48000)
    assert dst.exists()
    assert runner.calls, "ffmpeg runner was not called"
    args = runner.calls[0]
    assert "-c:a" in args and "libopus" in args
    assert "-b:a" in args and "128k" in args


def test_transcode_mp3_args(tmp_path):
    runner = FakeFfmpegRunner()
    src = tmp_path / "a.flac"; src.write_bytes(b"f")
    dst = tmp_path / "out.mp3"
    transcode(runner, src, dst, codec="mp3", bitrate_kbps=192, sample_rate_max=44100)
    args = runner.calls[0]
    assert "-map" in args and "0:v?" in args
    assert "-c:a" in args and "libmp3lame" in args
    assert "-id3v2_version" in args and "3" in args
    assert "-b:a" in args and "192k" in args


def test_transcode_aac_args(tmp_path):
    runner = FakeFfmpegRunner()
    src = tmp_path / "a.flac"; src.write_bytes(b"f")
    dst = tmp_path / "out.m4a"
    transcode(runner, src, dst, codec="aac", bitrate_kbps=128, sample_rate_max=48000)
    args = runner.calls[0]
    assert "-c:a" in args and "aac" in args
    assert "-movflags" in args and "+faststart" in args


def test_transcode_copy_does_not_invoke_ffmpeg(tmp_path):
    runner = FakeFfmpegRunner()
    src = tmp_path / "a.mp3"; src.write_bytes(b"copyme")
    dst = tmp_path / "out.mp3"
    transcode(runner, src, dst, codec="copy", bitrate_kbps=0, sample_rate_max=48000)
    assert dst.read_bytes() == b"copyme"
    assert runner.calls == []


def test_transcode_invalid_codec(tmp_path):
    runner = FakeFfmpegRunner()
    src = tmp_path / "a.mp3"; src.write_bytes(b"a")
    with pytest.raises(ValueError, match="codec"):
        transcode(runner, src, tmp_path / "out.xyz", codec="vorbis", bitrate_kbps=128, sample_rate_max=48000)


def test_transcode_rc_nonzero_raises(tmp_path):
    class FailingRunner:
        def run(self, args):
            return CompletedProcess(args, returncode=1, stdout=b"", stderr=b"ffmpeg failed: nope")

    src = tmp_path / "a.mp3"; src.write_bytes(b"a")
    with pytest.raises(TranscodeError, match="ffmpeg failed"):
        transcode(FailingRunner(), src, tmp_path / "out.opus",
                  codec="opus", bitrate_kbps=128, sample_rate_max=48000)
