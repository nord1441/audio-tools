from pathlib import Path
from subprocess import CompletedProcess

import pytest

from audio_tools.core.transcoder import (
    FakeFfmpegRunner,
    TranscodeError,
    transcode,
)
from audio_tools.core.transcoder import (
    TranscodeItem,
    TranscodeOutcome,
    batch_transcode,
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


def test_batch_transcode_runs_all_items(tmp_path):
    runner = FakeFfmpegRunner()
    items = []
    for i in range(3):
        src = tmp_path / f"in_{i}.mp3"; src.write_bytes(b"x")
        items.append(TranscodeItem(
            track_id=i,
            src=src,
            dst=tmp_path / f"out_{i}.opus",
            codec="opus",
            bitrate_kbps=128,
            sample_rate_max=48000,
        ))
    outcomes = list(batch_transcode(runner, items, workers=2))
    assert len(outcomes) == 3
    assert all(o.ok for o in outcomes)
    assert {o.track_id for o in outcomes} == {0, 1, 2}


def test_batch_transcode_collects_errors(tmp_path):
    class HalfFailingRunner:
        def __init__(self):
            self.calls = 0
        def run(self, args):
            self.calls += 1
            from subprocess import CompletedProcess
            if self.calls == 2:
                return CompletedProcess(args, returncode=1, stdout=b"", stderr=b"boom")
            import shutil
            try:
                i_idx = args.index("-i")
                shutil.copyfile(args[i_idx + 1], args[-1])
            except (ValueError, IndexError):
                pass
            return CompletedProcess(args, returncode=0, stdout=b"", stderr=b"")

    runner = HalfFailingRunner()
    items = [
        TranscodeItem(track_id=i, src=tmp_path / f"in_{i}.mp3",
                      dst=tmp_path / f"out_{i}.opus",
                      codec="opus", bitrate_kbps=128, sample_rate_max=48000)
        for i in range(3)
    ]
    for it in items:
        it.src.write_bytes(b"x")
    outcomes = list(batch_transcode(runner, items, workers=1))
    statuses = {o.track_id: o.ok for o in outcomes}
    assert statuses[1] is False
    assert sum(s for s in statuses.values()) == 2
