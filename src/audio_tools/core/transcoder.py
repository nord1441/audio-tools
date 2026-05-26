"""ffmpeg subprocess wrapper + transcode driver."""
import concurrent.futures as cf
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from typing import Iterable, Iterator, Protocol


ALLOWED_CODECS = frozenset({"opus", "mp3", "aac", "copy"})


class FfmpegRunner(Protocol):
    def run(self, args: list[str]) -> CompletedProcess: ...


class RealFfmpegRunner:
    """Real ffmpeg subprocess. Inject for production."""

    def __init__(self, binary: str = "ffmpeg"):
        self._binary = binary

    def run(self, args: list[str]) -> CompletedProcess:
        return subprocess.run(
            [self._binary, *args], check=False, capture_output=True
        )


class FakeFfmpegRunner:
    """Test double. Default behavior: copy source bytes to dst, return rc=0.
    Records every call's argv in self.calls.
    """

    def __init__(self):
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> CompletedProcess:
        self.calls.append(list(args))
        try:
            i_idx = args.index("-i")
            src = Path(args[i_idx + 1])
            dst = Path(args[-1])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        except (ValueError, IndexError, FileNotFoundError):
            pass
        return CompletedProcess(args, returncode=0, stdout=b"", stderr=b"")


class TranscodeError(Exception):
    def __init__(self, returncode: int, stderr: str):
        super().__init__(f"ffmpeg failed (rc={returncode}): {stderr.strip()}")
        self.returncode = returncode
        self.stderr = stderr


def _codec_args(codec: str, bitrate_kbps: int, sample_rate_max: int) -> list[str]:
    if codec == "opus":
        return [
            "-vn",
            "-c:a", "libopus",
            "-b:a", f"{bitrate_kbps}k",
            "-ar", str(min(48000, sample_rate_max)),
            "-ac", "2",
        ]
    if codec == "mp3":
        return [
            "-map", "0:a",
            "-map", "0:v?",
            "-c:v", "copy",
            "-c:a", "libmp3lame",
            "-b:a", f"{bitrate_kbps}k",
            "-id3v2_version", "3",
            "-write_id3v1", "0",
        ]
    if codec == "aac":
        return [
            "-map", "0:a",
            "-map", "0:v?",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", f"{bitrate_kbps}k",
            "-movflags", "+faststart",
        ]
    raise ValueError(f"unsupported codec for ffmpeg path: {codec!r}")


def transcode(
    runner: FfmpegRunner,
    src: Path,
    dst: Path,
    *,
    codec: str,
    bitrate_kbps: int,
    sample_rate_max: int,
) -> None:
    if codec not in ALLOWED_CODECS:
        raise ValueError(f"invalid codec: {codec!r}; allowed: {sorted(ALLOWED_CODECS)}")
    if codec == "copy":
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return

    args = [
        "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        *_codec_args(codec, bitrate_kbps, sample_rate_max),
        str(dst),
    ]
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = runner.run(args)
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        raise TranscodeError(result.returncode, stderr)


@dataclass(frozen=True)
class TranscodeItem:
    track_id: int
    src: Path
    dst: Path
    codec: str
    bitrate_kbps: int
    sample_rate_max: int


@dataclass(frozen=True)
class TranscodeOutcome:
    track_id: int
    ok: bool
    error: str | None = None


def batch_transcode(
    runner: FfmpegRunner,
    items: Iterable[TranscodeItem],
    *,
    workers: int,
) -> Iterator[TranscodeOutcome]:
    items_list = list(items)
    if not items_list:
        return iter([])

    def _one(it: TranscodeItem) -> TranscodeOutcome:
        try:
            transcode(
                runner, it.src, it.dst,
                codec=it.codec,
                bitrate_kbps=it.bitrate_kbps,
                sample_rate_max=it.sample_rate_max,
            )
            return TranscodeOutcome(track_id=it.track_id, ok=True)
        except Exception as e:
            return TranscodeOutcome(track_id=it.track_id, ok=False, error=str(e))

    if workers <= 1:
        return iter([_one(it) for it in items_list])

    def _iter() -> Iterator[TranscodeOutcome]:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_one, it) for it in items_list]
            for fut in cf.as_completed(futures):
                yield fut.result()

    return _iter()
