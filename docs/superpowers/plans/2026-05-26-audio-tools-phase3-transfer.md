# audio-tools Phase 3 (TransferPlanner + Transcoder + Transfer Execution) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver size-optimized music transfer to a device (USB or gvfs MTP path): bitrate planning, ffmpeg-driven transcoding, album-art preservation, rsync-style resume, and a `transfer_sessions` audit row per run. New CLI: `audio-tools transfer`.

**Architecture:** `core/transfer_planner.py` is pure-Python. `core/transcoder.py` wraps ffmpeg behind an `FfmpegRunner` protocol with real and fake implementations. `core/transfer_target.py` exposes `LocalDirectoryTarget` (single backend for both USB and gvfs MTP). `core/transfer.py` orchestrates transcode → sha1-skip copy → m3u write → session bookkeeping, with a SIGINT handler that marks the session `aborted`.

**Tech Stack:** Python 3.11+, ffmpeg subprocess, mutagen, Pillow (new dep — opus album art re-encoding), pytest. SQLAlchemy 2.0 + Alembic continue.

**Reference docs:**
- Parent spec: `docs/superpowers/specs/2026-05-25-audio-tools-design.md`
- Phase 3 spec addendum: `docs/superpowers/specs/2026-05-26-audio-tools-phase3-design.md`

---

## File Structure (Phase 3)

```
audio-tools/
├── pyproject.toml                                # Task 1 (Pillow dep)
├── alembic/versions/
│   └── 0005_create_transfer_sessions.py          # Task 3
├── src/audio_tools/
│   ├── cli.py                                    # Task 11
│   └── core/
│       ├── hashing.py                            # Task 1 (extracted helper)
│       ├── scanner.py                            # Task 1 (use new helper)
│       ├── models.py                             # Task 3 (+TransferSession)
│       ├── transfer_target.py                    # Task 2
│       ├── transfer_planner.py                   # Task 4
│       ├── transcoder.py                         # Tasks 5–6
│       ├── album_art.py                          # Task 7
│       ├── transfer.py                           # Tasks 8–9
│       └── m3u_path_style.py                     # Task 9
└── tests/
    ├── unit/
    │   ├── test_hashing.py                       # Task 1
    │   ├── test_transfer_target.py               # Task 2
    │   ├── test_transfer_planner.py              # Task 4
    │   ├── test_transcoder.py                    # Tasks 5–6
    │   ├── test_transfer.py                      # Task 8
    │   ├── test_m3u_path_style.py                # Task 9
    │   ├── test_db.py                            # Task 3 (+TransferSession)
    │   └── test_cli.py                           # Task 11
    └── golden/
        ├── test_transcoder_codecs.py             # Tasks 5–6 (real ffmpeg)
        └── test_album_art_preserved.py           # Task 7 (real ffmpeg + Pillow)
```

---

## Task 1: Extract `sha1_of` into `core/hashing.py`

The scanner sha1 helper is now needed by `transfer_target.LocalDirectoryTarget` too. Pull it out into a tiny shared module before either consumer grows.

**Files:**
- Create: `src/audio_tools/core/hashing.py`
- Modify: `src/audio_tools/core/scanner.py`
- Create: `tests/unit/test_hashing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_hashing.py
import hashlib
from pathlib import Path

from audio_tools.core.hashing import sha1_of


def test_sha1_of_matches_hashlib(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello world" * 1000)
    expected = hashlib.sha1(f.read_bytes()).hexdigest()
    assert sha1_of(f) == expected


def test_sha1_of_empty_file(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert sha1_of(f) == hashlib.sha1(b"").hexdigest()


def test_sha1_of_multi_chunk_file(tmp_path):
    # Forces multiple chunks through the 1 MiB read loop
    f = tmp_path / "big.bin"
    f.write_bytes(b"A" * (1024 * 1024 * 3 + 17))
    expected = hashlib.sha1(b"A" * (1024 * 1024 * 3 + 17)).hexdigest()
    assert sha1_of(f) == expected
```

- [ ] **Step 2: Verify failure**

```bash
source .venv/bin/activate
python -m pytest tests/unit/test_hashing.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `core/hashing.py`**

```python
# src/audio_tools/core/hashing.py
"""Filesystem hashing helpers shared by scanner and transfer modules."""
import hashlib
from pathlib import Path

_HASH_CHUNK = 1024 * 1024  # 1 MiB


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 4: Update `scanner.py` to use the shared helper**

In `src/audio_tools/core/scanner.py`:
- Remove the local `sha1_of` function and the `_HASH_CHUNK` constant and `import hashlib`.
- Add `from audio_tools.core.hashing import sha1_of`.

- [ ] **Step 5: Run the full suite**

```bash
python -m pytest -v
```
Expected: all prior tests pass (the scanner still uses the same algorithm via the shared helper) + 3 new hashing tests.

- [ ] **Step 6: Commit**

```bash
git add src/audio_tools/core/hashing.py src/audio_tools/core/scanner.py tests/unit/test_hashing.py
git commit -m "refactor(hashing): extract sha1_of into core/hashing for reuse"
```

---

## Task 2: `TransferTarget` protocol + `LocalDirectoryTarget`

**Files:**
- Create: `src/audio_tools/core/transfer_target.py`
- Create: `tests/unit/test_transfer_target.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_transfer_target.py
from pathlib import Path, PurePath

import pytest

from audio_tools.core.transfer_target import LocalDirectoryTarget


def test_local_target_requires_existing_directory(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        LocalDirectoryTarget(tmp_path / "missing")


def test_local_target_copy_and_exists(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    src = tmp_path / "src.mp3"
    src.write_bytes(b"hello")

    rel = PurePath("Music/foo/bar.mp3")
    assert not target.exists(rel)
    target.copy_file(src, rel)
    assert target.exists(rel)
    assert (root / "Music/foo/bar.mp3").read_bytes() == b"hello"


def test_local_target_file_sha1(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    src = tmp_path / "src.mp3"; src.write_bytes(b"hello")
    target.copy_file(src, PurePath("a.mp3"))

    import hashlib
    assert target.file_sha1(PurePath("a.mp3")) == hashlib.sha1(b"hello").hexdigest()
    assert target.file_sha1(PurePath("missing.mp3")) is None


def test_local_target_available_bytes(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    avail = target.available_bytes()
    assert isinstance(avail, int) and avail > 0


def test_local_target_remove_and_write_text(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    target.write_text(PurePath("playlists/p.m3u"), "#EXTM3U\n/abs/a.mp3\n")
    assert (root / "playlists/p.m3u").read_text() == "#EXTM3U\n/abs/a.mp3\n"
    target.remove(PurePath("playlists/p.m3u"))
    assert not target.exists(PurePath("playlists/p.m3u"))


def test_local_target_remove_missing_is_noop(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    target.remove(PurePath("nope.mp3"))  # must not raise
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_transfer_target.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `transfer_target.py`**

```python
# src/audio_tools/core/transfer_target.py
"""Transfer destinations: USB mounts, gvfs MTP paths.

LocalDirectoryTarget covers both because gvfs exposes MTP devices as ordinary
filesystem paths under /run/user/$UID/gvfs/. Future MTPTarget can be added
behind this same Protocol.
"""
import shutil
from pathlib import Path, PurePath
from typing import Protocol

from audio_tools.core.hashing import sha1_of


class TransferTarget(Protocol):
    def exists(self, relpath: PurePath) -> bool: ...
    def file_sha1(self, relpath: PurePath) -> str | None: ...
    def available_bytes(self) -> int: ...
    def copy_file(self, src: Path, relpath: PurePath) -> None: ...
    def remove(self, relpath: PurePath) -> None: ...
    def write_text(self, relpath: PurePath, text: str) -> None: ...


class LocalDirectoryTarget:
    """Target backed by an existing directory (USB mount, gvfs MTP, plain dir)."""

    def __init__(self, root: Path):
        root = Path(root)
        if not root.is_dir():
            raise ValueError(f"target root is not a directory: {root}")
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, relpath: PurePath) -> Path:
        return self._root / relpath

    def exists(self, relpath: PurePath) -> bool:
        return self._resolve(relpath).is_file()

    def file_sha1(self, relpath: PurePath) -> str | None:
        p = self._resolve(relpath)
        return sha1_of(p) if p.is_file() else None

    def available_bytes(self) -> int:
        return shutil.disk_usage(self._root).free

    def copy_file(self, src: Path, relpath: PurePath) -> None:
        dst = self._resolve(relpath)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def remove(self, relpath: PurePath) -> None:
        p = self._resolve(relpath)
        if p.is_file():
            p.unlink()

    def write_text(self, relpath: PurePath, text: str) -> None:
        dst = self._resolve(relpath)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_transfer_target.py -v
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/transfer_target.py tests/unit/test_transfer_target.py
git commit -m "feat(transfer_target): protocol + LocalDirectoryTarget (USB / gvfs MTP)"
```

---

## Task 3: `TransferSession` model + migration 0005

**Files:**
- Modify: `src/audio_tools/core/models.py`
- Create: `alembic/versions/0005_create_transfer_sessions.py`
- Modify: `tests/unit/test_db.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_db.py`:

```python
def test_transfer_session_insert_and_query(session):
    profile = DeviceProfile(
        name="walkman", codec="opus", container="ogg",
        max_bitrate=128, min_bitrate=64, bitrate_step=32,
        max_size_bytes=14_000_000_000, sample_rate_max=48000,
        m3u_path_style="relative", folder_layout="{artist}/{title}",
    )
    session.add(profile); session.flush()

    from audio_tools.core.models import TransferSession
    ts = TransferSession(
        profile_id=profile.id,
        started_at=datetime(2026, 5, 26, 13, 0, 0),
        status="running",
        bytes_transferred=0,
        bitrate_kbps=128,
        kept_count=42,
        dropped_count=3,
    )
    session.add(ts); session.commit()

    fetched = session.get(TransferSession, ts.id)
    assert fetched.status == "running"
    assert fetched.bitrate_kbps == 128
    assert fetched.kept_count == 42
    assert fetched.profile_id == profile.id
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_db.py -v
```
Expected: FAIL (`ImportError: cannot import name 'TransferSession'`).

- [ ] **Step 3: Add `TransferSession` model**

Append to `src/audio_tools/core/models.py`:

```python
class TransferSession(Base):
    __tablename__ = "transfer_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("device_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # running|completed|aborted|failed
    bytes_transferred: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bitrate_kbps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kept_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dropped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Generate migration**

```bash
rm -f /tmp/at_test_migration.db
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic upgrade head
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic revision --autogenerate -m "create transfer_sessions table" --rev-id 0005 --depends-on 0004
```

Inspect `alembic/versions/0005_create_transfer_sessions.py`. Confirm it contains exactly one `op.create_table('transfer_sessions', …)` with the FK on `device_profiles.id`. Trim any spurious ops.

- [ ] **Step 5: Verify migration applies**

```bash
rm -f /tmp/at_test_migration.db
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic upgrade head
sqlite3 /tmp/at_test_migration.db ".schema transfer_sessions"
```
Expected: full schema with FK + all columns.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/unit/test_db.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/audio_tools/core/models.py alembic/versions/0005_create_transfer_sessions.py tests/unit/test_db.py
git commit -m "feat(db): add TransferSession model and migration"
```

---

## Task 4: `TransferPlanner.plan`

**Files:**
- Create: `src/audio_tools/core/transfer_planner.py`
- Create: `tests/unit/test_transfer_planner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_transfer_planner.py
from dataclasses import dataclass
from pathlib import Path

import pytest

from audio_tools.core.transfer_planner import (
    PlannedTrack,
    TransferPlan,
    TransferPlanError,
    plan,
)


@dataclass
class FakeTrack:
    id: int
    path: str
    size: int
    duration_s: float | None


@dataclass
class FakeProfile:
    codec: str
    max_bitrate: int
    min_bitrate: int
    bitrate_step: int
    max_size_bytes: int


def _track(track_id: int, duration: float, size: int = 1000) -> FakeTrack:
    return FakeTrack(id=track_id, path=f"/m/{track_id}.mp3", size=size, duration_s=duration)


def _profile(codec="opus", max_b=128, min_b=64, step=32, cap=10_000_000) -> FakeProfile:
    return FakeProfile(
        codec=codec, max_bitrate=max_b, min_bitrate=min_b,
        bitrate_step=step, max_size_bytes=cap,
    )


def test_plan_fits_at_max_bitrate():
    tracks = [_track(i, duration=180.0) for i in range(3)]
    p = _profile(cap=10_000_000)  # 10 MB, easily fits 3*180s*128kbps
    out = plan(tracks, p)
    assert out.bitrate_kbps == 128
    assert len(out.kept) == 3 and not out.dropped


def test_plan_drops_to_lower_bitrate():
    tracks = [_track(i, duration=180.0) for i in range(50)]
    # ~50 * 180s * 128kbps / 8 * 1.05 = ~151MB; cap below that forces a step down
    p = _profile(cap=100_000_000)
    out = plan(tracks, p)
    assert out.bitrate_kbps < 128 and out.bitrate_kbps >= 64
    assert len(out.kept) == 50 and not out.dropped


def test_plan_drops_tail_when_even_min_overflows():
    tracks = [_track(i, duration=180.0) for i in range(50)]
    # 50 * 180s * 64kbps / 8 * 1.05 = ~76MB; cap=40MB drops about half
    p = _profile(cap=40_000_000)
    out = plan(tracks, p)
    assert out.bitrate_kbps == 64
    assert len(out.kept) + len(out.dropped) == 50
    assert len(out.dropped) > 0
    # Tail-drop ordering: dropped tracks are from the END of the input list
    dropped_ids = [t.track_id for t in out.dropped]
    assert dropped_ids == sorted(dropped_ids, reverse=False)  # input order preserved within dropped


def test_plan_copy_codec_uses_source_sizes():
    tracks = [_track(i, duration=180.0, size=2_000_000) for i in range(3)]
    p = _profile(codec="copy", cap=10_000_000)
    out = plan(tracks, p)
    assert out.bitrate_kbps == 0
    assert all(pt.output_size_bytes == 2_000_000 for pt in out.kept)


def test_plan_copy_codec_drops_when_oversize():
    tracks = [_track(i, duration=180.0, size=4_000_000) for i in range(5)]  # 20MB total
    p = _profile(codec="copy", cap=10_000_000)
    out = plan(tracks, p)
    assert len(out.kept) <= 2
    assert len(out.dropped) >= 3


def test_plan_track_with_none_duration_falls_back_to_size():
    tracks = [
        _track(1, duration=180.0, size=1_000_000),
        FakeTrack(id=2, path="/m/2.mp3", size=2_000_000, duration_s=None),
    ]
    p = _profile(cap=50_000_000)
    out = plan(tracks, p)
    ids = {pt.track_id for pt in out.kept}
    assert ids == {1, 2}


def test_plan_empty_input():
    out = plan([], _profile())
    assert out.kept == [] and out.dropped == []


def test_plan_invalid_profile_min_gt_max():
    p = _profile(max_b=64, min_b=128)
    with pytest.raises(TransferPlanError, match="min_bitrate"):
        plan([_track(1, 180.0)], p)


def test_plan_invalid_profile_zero_step():
    p = _profile(step=0)
    with pytest.raises(TransferPlanError, match="bitrate_step"):
        plan([_track(1, 180.0)], p)


def test_plan_returns_total_bytes_for_kept():
    tracks = [_track(i, duration=180.0, size=2_000_000) for i in range(3)]
    out = plan(tracks, _profile(codec="copy", cap=10_000_000))
    assert out.total_kept_bytes == sum(t.size for t in tracks)
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_transfer_planner.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `transfer_planner.py`**

```python
# src/audio_tools/core/transfer_planner.py
"""Pure-Python bitrate + tail-drop search. No I/O, no DB."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class _TrackLike(Protocol):
    id: int
    path: str
    size: int
    duration_s: float | None


class _ProfileLike(Protocol):
    codec: str
    max_bitrate: int
    min_bitrate: int
    bitrate_step: int
    max_size_bytes: int


@dataclass(frozen=True)
class PlannedTrack:
    track_id: int
    source_path: Path
    output_size_bytes: int
    codec: str
    bitrate_kbps: int  # 0 when codec='copy'


@dataclass
class TransferPlan:
    bitrate_kbps: int  # 0 when codec='copy'
    kept: list[PlannedTrack]
    dropped: list[PlannedTrack]
    total_kept_bytes: int
    warnings: list[str] = field(default_factory=list)


class TransferPlanError(ValueError):
    pass


def _predict(track: _TrackLike, codec: str, bitrate_kbps: int) -> int:
    if codec == "copy":
        return track.size
    if track.duration_s is None:
        return track.size  # fallback; warning emitted at the call site
    bits = track.duration_s * bitrate_kbps * 1000.0
    return int(bits / 8 * 1.05)


def _build_planned(tracks: list[_TrackLike], codec: str, bitrate_kbps: int) -> list[PlannedTrack]:
    return [
        PlannedTrack(
            track_id=t.id,
            source_path=Path(t.path),
            output_size_bytes=_predict(t, codec, bitrate_kbps),
            codec=codec,
            bitrate_kbps=0 if codec == "copy" else bitrate_kbps,
        )
        for t in tracks
    ]


def _drop_from_tail(planned: list[PlannedTrack], cap: int) -> tuple[list[PlannedTrack], list[PlannedTrack]]:
    """Drop tail entries one at a time until the kept total fits under cap."""
    kept = list(planned)
    dropped: list[PlannedTrack] = []
    total = sum(p.output_size_bytes for p in kept)
    while kept and total > cap:
        d = kept.pop()  # pop from END
        dropped.append(d)
        total -= d.output_size_bytes
    return kept, list(reversed(dropped))  # dropped preserves input order


def plan(tracks: list[_TrackLike], profile: _ProfileLike) -> TransferPlan:
    if profile.min_bitrate > profile.max_bitrate:
        raise TransferPlanError(
            f"min_bitrate ({profile.min_bitrate}) > max_bitrate ({profile.max_bitrate})"
        )
    if profile.bitrate_step <= 0:
        raise TransferPlanError(f"bitrate_step must be > 0, got {profile.bitrate_step}")

    if not tracks:
        return TransferPlan(bitrate_kbps=0, kept=[], dropped=[], total_kept_bytes=0)

    warnings: list[str] = []
    if any(t.duration_s is None for t in tracks):
        warnings.append("some tracks have no duration; sizes estimated from source bytes")

    codec = profile.codec
    if codec == "copy":
        planned = _build_planned(tracks, codec="copy", bitrate_kbps=0)
        kept, dropped = _drop_from_tail(planned, profile.max_size_bytes)
        return TransferPlan(
            bitrate_kbps=0,
            kept=kept, dropped=dropped,
            total_kept_bytes=sum(p.output_size_bytes for p in kept),
            warnings=warnings,
        )

    # Try max_bitrate, max_bitrate - step, ..., min_bitrate.
    bitrate = profile.max_bitrate
    chosen_planned: list[PlannedTrack] | None = None
    while bitrate >= profile.min_bitrate:
        planned = _build_planned(tracks, codec=codec, bitrate_kbps=bitrate)
        total = sum(p.output_size_bytes for p in planned)
        if total <= profile.max_size_bytes:
            chosen_planned = planned
            break
        bitrate -= profile.bitrate_step

    if chosen_planned is None:
        # Even at min_bitrate it overflows → drop tail at min_bitrate.
        bitrate = profile.min_bitrate
        planned = _build_planned(tracks, codec=codec, bitrate_kbps=bitrate)
        kept, dropped = _drop_from_tail(planned, profile.max_size_bytes)
        return TransferPlan(
            bitrate_kbps=bitrate,
            kept=kept, dropped=dropped,
            total_kept_bytes=sum(p.output_size_bytes for p in kept),
            warnings=warnings,
        )

    return TransferPlan(
        bitrate_kbps=bitrate,
        kept=chosen_planned,
        dropped=[],
        total_kept_bytes=sum(p.output_size_bytes for p in chosen_planned),
        warnings=warnings,
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_transfer_planner.py -v
```
Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/transfer_planner.py tests/unit/test_transfer_planner.py
git commit -m "feat(transfer_planner): pure-Python bitrate + tail-drop search"
```

---

## Task 5: `FfmpegRunner` protocol + `RealFfmpegRunner` + `FakeFfmpegRunner` + single-file `transcode()`

**Files:**
- Create: `src/audio_tools/core/transcoder.py`
- Create: `tests/unit/test_transcoder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_transcoder.py
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
    # Must passthrough image stream and tag with id3v2 v3
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
    assert runner.calls == []  # copy path is shutil-based


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
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_transcoder.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `transcoder.py` (single-file path)**

```python
# src/audio_tools/core/transcoder.py
"""ffmpeg subprocess wrapper + transcode driver.

`FfmpegRunner` is a thin Protocol so tests can swap a fake. `RealFfmpegRunner`
calls subprocess.run("ffmpeg", *args). `transcode()` builds codec-specific argv
and dispatches; `copy` codec bypasses ffmpeg entirely via shutil.
"""
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from typing import Iterable, Protocol


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
        # Locate -i SRC and trailing DST
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
            "-vn",  # opus path: image preserved later by mutagen
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_transcoder.py -v
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/transcoder.py tests/unit/test_transcoder.py
git commit -m "feat(transcoder): FfmpegRunner protocol + single-file transcode()"
```

---

## Task 6: `batch_transcode()` + threadpool + golden test

**Files:**
- Modify: `src/audio_tools/core/transcoder.py`
- Modify: `tests/unit/test_transcoder.py`
- Create: `tests/golden/test_transcoder_codecs.py`

- [ ] **Step 1: Append batch tests** to `tests/unit/test_transcoder.py`:

```python
from audio_tools.core.transcoder import (
    TranscodeItem,
    TranscodeOutcome,
    batch_transcode,
)


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
            # Mirror FakeFfmpegRunner copy behavior on success
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
    outcomes = list(batch_transcode(runner, items, workers=1))  # serialize for determinism
    statuses = {o.track_id: o.ok for o in outcomes}
    assert statuses[1] is False
    assert sum(s for s in statuses.values()) == 2  # two succeeded
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_transcoder.py -v
```
Expected: 2 new tests FAIL (`ImportError`).

- [ ] **Step 3: Implement `batch_transcode()` (append to transcoder.py)**

```python
import concurrent.futures as cf
from typing import Iterable, Iterator


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
```

- [ ] **Step 4: Run unit tests**

```bash
python -m pytest tests/unit/test_transcoder.py -v
```
Expected: all transcoder unit tests pass.

- [ ] **Step 5: Add golden codec tests**

Create `tests/golden/test_transcoder_codecs.py`:

```python
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
```

- [ ] **Step 6: Run golden tests (will pass with ffmpeg installed)**

```bash
python -m pytest tests/golden/test_transcoder_codecs.py -v
```
Expected: 3 PASS (assuming ffmpeg is on PATH) or SKIPPED.

- [ ] **Step 7: Commit**

```bash
git add src/audio_tools/core/transcoder.py tests/unit/test_transcoder.py tests/golden/test_transcoder_codecs.py
git commit -m "feat(transcoder): ThreadPool batch driver + real-ffmpeg golden tests"
```

---

## Task 7: Album art preservation (`core/album_art.py`)

**Files:**
- Modify: `pyproject.toml` (add `Pillow`)
- Create: `src/audio_tools/core/album_art.py`
- Create: `tests/golden/test_album_art_preserved.py`

- [ ] **Step 1: Add Pillow to dependencies**

In `pyproject.toml`, append `"Pillow>=10.0",` to `[project] dependencies`. Re-install:

```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Write the failing golden test**

Create `tests/golden/test_album_art_preserved.py`:

```python
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
    # 1x1 red JPEG via ffmpeg
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
        # opus path must explicitly embed; expect True
        assert preserved is True
    # All three codecs should produce a readable picture after preservation
    assert _has_picture(dst, codec), f"no picture in {dst}"
```

- [ ] **Step 3: Verify failure**

```bash
python -m pytest tests/golden/test_album_art_preserved.py -v
```
Expected: FAIL (`ModuleNotFoundError`) or SKIPPED on no-ffmpeg systems.

- [ ] **Step 4: Implement `album_art.py`**

```python
# src/audio_tools/core/album_art.py
"""Preserve embedded album art across transcodes.

mp3/aac/copy: rely on ffmpeg's `-map 0:v?` passthrough. This module then
*verifies* the picture survived and logs a warning if not.

opus: extract the picture from the source via mutagen, re-encode to JPEG if
necessary, base64-encode into a Vorbis `METADATA_BLOCK_PICTURE` comment.
"""
import base64
import io
import struct
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
    # ID3 (mp3, sometimes m4a containers)
    if isinstance(mf.tags, ID3):
        for frame in mf.tags.values():
            if isinstance(frame, APIC):
                return bytes(frame.data), frame.mime or "image/jpeg"
    # MP4
    covers = mf.tags.get("covr") if mf.tags else None
    if covers:
        cover = covers[0]
        fmt = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        return bytes(cover), fmt
    # Opus / Vorbis: METADATA_BLOCK_PICTURE
    block = mf.get("metadata_block_picture")
    if block:
        data = base64.b64decode(block[0])
        pic = FlacPicture(data)
        return bytes(pic.data), pic.mime or "image/jpeg"
    # FLAC: .pictures
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
    pic.type = 3  # cover (front)
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
    """Ensure dst carries the same album art as src for the given output codec.

    Returns True if a picture was preserved (either passthrough-verified or
    explicitly embedded), False otherwise.
    """
    if codec == "copy":
        return True  # file is byte-identical, nothing to do

    extracted = _extract_picture_bytes(src)
    if extracted is None:
        return False
    image_bytes, mime = extracted

    if codec in ("mp3", "aac"):
        # ffmpeg's -map 0:v? should have passed the image through; verify.
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
```

- [ ] **Step 5: Run golden test**

```bash
python -m pytest tests/golden/test_album_art_preserved.py -v
```
Expected: 3 PASS (or SKIPPED on no-ffmpeg).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/audio_tools/core/album_art.py tests/golden/test_album_art_preserved.py
git commit -m "feat(album_art): preserve embedded picture across mp3/aac/opus transcodes"
```

---

## Task 8: Transfer orchestration (`core/transfer.py`)

**Files:**
- Create: `src/audio_tools/core/transfer.py`
- Create: `tests/unit/test_transfer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_transfer.py
from datetime import datetime
from pathlib import Path, PurePath

import pytest
from sqlalchemy import select

from audio_tools.core.models import (
    DeviceProfile,
    Track,
    TransferSession,
)
from audio_tools.core.transcoder import FakeFfmpegRunner
from audio_tools.core.transfer import TransferOutcome, execute_transfer
from audio_tools.core.transfer_planner import (
    PlannedTrack,
    TransferPlan,
)
from audio_tools.core.transfer_target import LocalDirectoryTarget


def _profile(session, **kwargs) -> DeviceProfile:
    defaults = dict(
        name="dev", codec="opus", container="ogg",
        max_bitrate=128, min_bitrate=64, bitrate_step=32,
        max_size_bytes=1_000_000_000, sample_rate_max=48000,
        m3u_path_style="relative",
        folder_layout="{artist}/{title}",
    )
    defaults.update(kwargs)
    p = DeviceProfile(**defaults)
    session.add(p); session.flush()
    return p


def _track(session, **kwargs) -> Track:
    defaults = dict(path="/m/song.mp3", mtime=0.0, size=1000,
                    title="Song", artist="Artist", duration_s=180.0)
    defaults.update(kwargs)
    t = Track(**defaults)
    session.add(t); session.flush()
    return t


def _plan_from(tracks: list[Track], codec="opus", bitrate=96) -> TransferPlan:
    kept = [
        PlannedTrack(
            track_id=t.id, source_path=Path(t.path),
            output_size_bytes=t.size, codec=codec, bitrate_kbps=bitrate,
        )
        for t in tracks
    ]
    return TransferPlan(
        bitrate_kbps=bitrate, kept=kept, dropped=[],
        total_kept_bytes=sum(t.size for t in tracks),
    )


def test_execute_transfer_happy_path(tmp_path, session):
    src = tmp_path / "song.mp3"; src.write_bytes(b"audio bytes")
    track = _track(session, path=str(src))
    profile = _profile(session)
    target_root = tmp_path / "device"; target_root.mkdir()
    target = LocalDirectoryTarget(target_root)
    runner = FakeFfmpegRunner()

    out = execute_transfer(
        session=session,
        profile=profile,
        plan=_plan_from([track]),
        target=target,
        ffmpeg=runner,
        m3u_relpath=PurePath("Playlists/all.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert isinstance(out, TransferOutcome)
    assert out.copied == 1 and out.skipped == 0 and out.failed == 0

    # File appears under folder_layout
    assert (target_root / "Artist" / "Song.opus").exists()

    # Session row written and completed
    rows = session.scalars(select(TransferSession)).all()
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].kept_count == 1
    assert rows[0].dropped_count == 0
    assert rows[0].finished_at is not None
    assert rows[0].bytes_transferred > 0

    # m3u written
    m3u_text = (target_root / "Playlists/all.m3u").read_text()
    assert "Artist/Song.opus" in m3u_text  # relative path style


def test_execute_transfer_skips_existing_sha1_match(tmp_path, session):
    src = tmp_path / "song.mp3"; src.write_bytes(b"audio bytes")
    track = _track(session, path=str(src))
    profile = _profile(session)
    target_root = tmp_path / "device"; target_root.mkdir()
    target = LocalDirectoryTarget(target_root)
    runner = FakeFfmpegRunner()

    out1 = execute_transfer(
        session=session, profile=profile, plan=_plan_from([track]),
        target=target, ffmpeg=runner,
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert out1.copied == 1

    out2 = execute_transfer(
        session=session, profile=profile, plan=_plan_from([track]),
        target=target, ffmpeg=runner,
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache2",
    )
    assert out2.skipped == 1 and out2.copied == 0


def test_execute_transfer_failed_track_continues(tmp_path, session):
    from subprocess import CompletedProcess

    src_a = tmp_path / "a.mp3"; src_a.write_bytes(b"good")
    src_b = tmp_path / "b.mp3"; src_b.write_bytes(b"bad")
    tracks = [_track(session, path=str(src_a), title="A"),
              _track(session, path=str(src_b), title="B")]
    profile = _profile(session)
    target_root = tmp_path / "device"; target_root.mkdir()
    target = LocalDirectoryTarget(target_root)

    class BRunner:
        def run(self, args):
            if "b.mp3" in " ".join(args):
                return CompletedProcess(args, returncode=1, stdout=b"", stderr=b"bad")
            import shutil
            i_idx = args.index("-i")
            shutil.copyfile(args[i_idx + 1], args[-1])
            return CompletedProcess(args, returncode=0, stdout=b"", stderr=b"")

    out = execute_transfer(
        session=session, profile=profile, plan=_plan_from(tracks),
        target=target, ffmpeg=BRunner(),
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert out.copied == 1 and out.failed == 1
    row = session.scalars(select(TransferSession)).first()
    assert row.status == "completed"  # below 50% threshold


def test_execute_transfer_majority_failed_marks_failed(tmp_path, session):
    from subprocess import CompletedProcess

    tracks = []
    for i in range(4):
        src = tmp_path / f"t{i}.mp3"; src.write_bytes(b"x")
        tracks.append(_track(session, path=str(src), title=f"T{i}"))

    class AllBadRunner:
        def run(self, args):
            return CompletedProcess(args, returncode=1, stdout=b"", stderr=b"boom")

    target_root = tmp_path / "device"; target_root.mkdir()
    out = execute_transfer(
        session=session, profile=_profile(session),
        plan=_plan_from(tracks),
        target=LocalDirectoryTarget(target_root),
        ffmpeg=AllBadRunner(),
        m3u_relpath=PurePath("p.m3u"),
        cache_dir=tmp_path / "cache",
    )
    assert out.failed == 4
    row = session.scalars(select(TransferSession)).first()
    assert row.status == "failed"
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_transfer.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `transfer.py`**

```python
# src/audio_tools/core/transfer.py
"""Transfer orchestration: transcode → sha1-skip copy → m3u write → session row."""
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePath
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from audio_tools.core import album_art as album_art_mod
from audio_tools.core.hashing import sha1_of
from audio_tools.core.models import DeviceProfile, Track, TransferSession
from audio_tools.core.transcoder import (
    FfmpegRunner,
    TranscodeError,
    TranscodeItem,
    TranscodeOutcome,
    batch_transcode,
)
from audio_tools.core.transfer_planner import PlannedTrack, TransferPlan
from audio_tools.core.transfer_target import TransferTarget


CODEC_EXTENSIONS = {"opus": ".opus", "mp3": ".mp3", "aac": ".m4a", "copy": ""}


@dataclass
class TransferOutcome:
    session_id: int
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _ext_for_codec(codec: str, source_path: Path) -> str:
    if codec == "copy":
        return source_path.suffix
    return CODEC_EXTENSIONS[codec]


def _build_relpath(profile: DeviceProfile, track: Track, codec: str) -> PurePath:
    fields = {
        "artist": (track.artist or "Unknown Artist"),
        "album": (track.album or "Unknown Album"),
        "title": (track.title or Path(track.path).stem),
        "track": 0,  # track number not yet captured in Phase 1 tags
    }
    layout = profile.folder_layout.format(**fields)
    # Sanitize each component so layout can't escape via "/.."
    safe_parts = []
    for part in PurePath(layout).parts:
        safe_parts.append(part.replace("/", "_").replace("\\", "_"))
    safe = PurePath(*safe_parts)
    return safe.with_suffix(_ext_for_codec(codec, Path(track.path)))


def _format_m3u(
    profile: DeviceProfile,
    items: list[tuple[Track, PurePath]],
) -> str:
    from audio_tools.core import m3u_path_style as styles

    lines = ["#EXTM3U"]
    for track, relpath in items:
        duration = int(track.duration_s) if track.duration_s is not None else -1
        artist = track.artist or ""
        title = track.title or Path(track.path).stem
        lines.append(f"#EXTINF:{duration},{artist} - {title}")
        lines.append(styles.format_path(relpath, profile.m3u_path_style))
    lines.append("")
    return "\n".join(lines)


def execute_transfer(
    *,
    session: Session,
    profile: DeviceProfile,
    plan: TransferPlan,
    target: TransferTarget,
    ffmpeg: FfmpegRunner,
    m3u_relpath: PurePath,
    cache_dir: Path,
    workers: int = 1,
    keep_temp: bool = False,
) -> TransferOutcome:
    cache_dir.mkdir(parents=True, exist_ok=True)

    ts = TransferSession(
        profile_id=profile.id,
        started_at=datetime.utcnow(),
        status="running",
        bytes_transferred=0,
        bitrate_kbps=plan.bitrate_kbps if plan.bitrate_kbps else None,
        kept_count=len(plan.kept),
        dropped_count=len(plan.dropped),
    )
    session.add(ts); session.commit()
    outcome = TransferOutcome(session_id=ts.id)

    # Build TranscodeItem batch + track relpath map
    relpaths: dict[int, PurePath] = {}
    items: list[TranscodeItem] = []
    track_lookup: dict[int, Track] = {}
    for planned in plan.kept:
        track = session.get(Track, planned.track_id)
        if track is None:
            outcome.failed += 1
            outcome.errors.append(f"track id={planned.track_id} not found")
            continue
        track_lookup[track.id] = track
        relpath = _build_relpath(profile, track, planned.codec)
        relpaths[track.id] = relpath
        ext = _ext_for_codec(planned.codec, Path(track.path))
        staged = cache_dir / f"{track.id}{ext}"
        items.append(TranscodeItem(
            track_id=track.id,
            src=Path(track.path),
            dst=staged,
            codec=planned.codec,
            bitrate_kbps=planned.bitrate_kbps,
            sample_rate_max=profile.sample_rate_max,
        ))

    successful_tracks: list[Track] = []
    for r in batch_transcode(ffmpeg, items, workers=workers):
        track = track_lookup[r.track_id]
        if not r.ok:
            outcome.failed += 1
            outcome.errors.append(f"{track.path}: {r.error}")
            continue

        # Album art preservation (best-effort)
        item = next(i for i in items if i.track_id == r.track_id)
        try:
            album_art_mod.preserve_album_art(item.src, item.dst, item.codec)
        except Exception as e:  # pragma: no cover -- best-effort
            outcome.errors.append(f"art preserve {track.path}: {e}")

        relpath = relpaths[track.id]
        staged_sha1 = sha1_of(item.dst)
        if target.exists(relpath) and target.file_sha1(relpath) == staged_sha1:
            outcome.skipped += 1
        else:
            target.copy_file(item.dst, relpath)
            ts.bytes_transferred += item.dst.stat().st_size
            outcome.copied += 1
        successful_tracks.append(track)

    if successful_tracks:
        m3u_text = _format_m3u(profile, [(t, relpaths[t.id]) for t in successful_tracks])
        target.write_text(m3u_relpath, m3u_text)

    total_attempted = outcome.copied + outcome.skipped + outcome.failed
    if total_attempted and outcome.failed / total_attempted > 0.5:
        ts.status = "failed"
        ts.error = "; ".join(outcome.errors[:5])
    else:
        ts.status = "completed"
    ts.finished_at = datetime.utcnow()
    session.commit()

    if not keep_temp:
        shutil.rmtree(cache_dir, ignore_errors=True)

    return outcome
```

- [ ] **Step 4: Add the `m3u_path_style` helper (referenced above)**

Create `src/audio_tools/core/m3u_path_style.py`:

```python
"""Render a track relpath into an m3u line per the device profile's preference."""
from pathlib import PurePath

ALLOWED = frozenset({"relative", "windows_backslash", "absolute"})


def format_path(relpath: PurePath, style: str) -> str:
    if style == "relative":
        return str(relpath)
    if style == "windows_backslash":
        return str(relpath).replace("/", "\\")
    if style == "absolute":
        # On the device, paths are always relative to its root; "absolute"
        # means "begin with /". The caller (transfer.py) hands us device-relative
        # paths; we prefix with the device-local root '/'.
        return "/" + str(relpath)
    raise ValueError(f"unknown m3u_path_style: {style!r}")
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/unit/test_transfer.py -v
```
Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/audio_tools/core/transfer.py src/audio_tools/core/m3u_path_style.py tests/unit/test_transfer.py
git commit -m "feat(transfer): orchestrate transcode + sha1-skip copy + session"
```

---

## Task 9: `m3u_path_style` unit tests + path traversal hardening

**Files:**
- Create: `tests/unit/test_m3u_path_style.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/test_m3u_path_style.py
from pathlib import PurePath

import pytest

from audio_tools.core.m3u_path_style import format_path


def test_relative():
    assert format_path(PurePath("Music/foo.mp3"), "relative") == "Music/foo.mp3"


def test_windows_backslash():
    assert format_path(PurePath("Music/foo/bar.mp3"), "windows_backslash") == "Music\\foo\\bar.mp3"


def test_absolute_prefixes_slash():
    assert format_path(PurePath("Music/foo.mp3"), "absolute") == "/Music/foo.mp3"


def test_unknown_style_raises():
    with pytest.raises(ValueError, match="unknown m3u_path_style"):
        format_path(PurePath("foo.mp3"), "weird")
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/unit/test_m3u_path_style.py -v
```
Expected: 4 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_m3u_path_style.py
git commit -m "test(m3u_path_style): cover all 3 style branches + unknown rejection"
```

---

## Task 10: `transfer` CLI subcommand

**Files:**
- Modify: `src/audio_tools/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_cli.py`:

```python
def test_cli_transfer_dry_run(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"; music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    shutil.copy(FIXTURE_MP3, music / "b.mp3")

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")

    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    # Set up a profile via YAML loader
    profiles_dir = tmp_path / "profiles"; profiles_dir.mkdir()
    (profiles_dir / "tiny.yaml").write_text(
        "name: tiny\n"
        "codec: opus\n"
        "container: ogg\n"
        "max_bitrate: 96\n"
        "min_bitrate: 64\n"
        "bitrate_step: 32\n"
        "max_size_bytes: 100000\n"   # tiny: 100KB → drops expected
        "sample_rate_max: 48000\n"
        "m3u_path_style: relative\n"
        "folder_layout: \"{title}\"\n"
    )

    runner = CliRunner()
    runner.invoke(main, ["scan", str(music)])
    runner.invoke(main, ["analyze", "--backend=fake"])
    runner.invoke(main, ["cluster", "--k=2", "--force"])

    target_dir = tmp_path / "device"; target_dir.mkdir()
    result = runner.invoke(main, [
        "transfer",
        "--profile", "tiny",
        "--profile-dir", str(profiles_dir),
        "--playlist", "Cluster 1",
        "--target-dir", str(target_dir),
        "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "bitrate=" in result.output
    # Dry run must not write to the device
    assert not list(target_dir.iterdir())


def test_cli_transfer_executes_and_writes_files(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"; music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_FFMPEG", "1")

    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    profiles_dir = tmp_path / "profiles"; profiles_dir.mkdir()
    (profiles_dir / "p.yaml").write_text(
        "name: p\n"
        "codec: opus\n"
        "container: ogg\n"
        "max_bitrate: 96\n"
        "min_bitrate: 64\n"
        "bitrate_step: 32\n"
        "max_size_bytes: 100000000\n"
        "sample_rate_max: 48000\n"
        "m3u_path_style: relative\n"
        "folder_layout: \"{title}\"\n"
    )

    runner = CliRunner()
    runner.invoke(main, ["scan", str(music)])
    runner.invoke(main, ["analyze", "--backend=fake"])
    runner.invoke(main, ["cluster", "--k=2", "--force"])

    target_dir = tmp_path / "device"; target_dir.mkdir()
    result = runner.invoke(main, [
        "transfer",
        "--profile", "p",
        "--profile-dir", str(profiles_dir),
        "--playlist", "Cluster 1",
        "--target-dir", str(target_dir),
        "--ffmpeg-backend", "fake",
        "--yes",
    ])
    assert result.exit_code == 0, result.output
    # At least one .opus or .m3u was written
    written = list(target_dir.rglob("*"))
    assert any(p.is_file() for p in written)
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: 2 new tests FAIL.

- [ ] **Step 3: Implement `transfer` command**

Append to `src/audio_tools/cli.py`:

```python
from pathlib import PurePath as _PurePath

from audio_tools.core import device_profile as dp_mod
from audio_tools.core import transfer as transfer_mod
from audio_tools.core.models import (
    Cluster as _ClusterModel,
    ClusterAssignment as _ClusterAssignment,
    DeviceProfile as _DeviceProfile,
)
from audio_tools.core.transcoder import FakeFfmpegRunner, RealFfmpegRunner
from audio_tools.core.transfer_planner import plan as _plan
from audio_tools.core.transfer_target import LocalDirectoryTarget


def _build_ffmpeg_runner(name: str):
    if name == "fake":
        if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_FFMPEG") != "1":
            raise click.UsageError(
                "fake ffmpeg disabled. Set AUDIO_TOOLS_ALLOW_FAKE_FFMPEG=1 to enable."
            )
        return FakeFfmpegRunner()
    if name == "real":
        return RealFfmpegRunner()
    raise click.UsageError(f"Unknown ffmpeg backend: {name}")


def _load_profile(session, name: str, profile_dir: Optional[Path]) -> _DeviceProfile:
    existing = session.scalar(select(_DeviceProfile).where(_DeviceProfile.name == name))
    if existing is not None:
        return existing
    pdir = profile_dir or paths_mod.device_profiles_dir()
    yaml_path = pdir / f"{name}.yaml"
    if not yaml_path.exists():
        raise click.UsageError(f"Profile {name!r} not in DB and {yaml_path} does not exist")
    return dp_mod.upsert_profile(yaml_path, session)


def _collect_tracks_for_playlists(session, playlist_names: tuple[str, ...]) -> list:
    """Resolve cluster names to ordered (per spec: nearest-centroid first) tracks."""
    from audio_tools.core.models import Track as _Track
    out: list = []
    for name in playlist_names:
        cluster = session.scalar(select(_ClusterModel).where(_ClusterModel.name == name))
        if cluster is None:
            raise click.UsageError(f"No cluster named {name!r}")
        stmt = (
            select(_Track)
            .join(_ClusterAssignment, _ClusterAssignment.track_id == _Track.id)
            .where(_ClusterAssignment.cluster_id == cluster.id)
            .order_by(_ClusterAssignment.distance.asc())
        )
        out.extend(session.scalars(stmt).all())
    return out


@main.command()
@click.option("--profile", "profile_name", required=True)
@click.option("--profile-dir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--playlist", "playlists", multiple=True, required=True)
@click.option("--target-dir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--workers", type=int, default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--keep-temp", is_flag=True)
@click.option("--yes", is_flag=True, help="Skip the drop-confirmation prompt.")
@click.option("--ffmpeg-backend", type=click.Choice(["real", "fake"]), default="real")
def transfer(
    profile_name: str,
    profile_dir: Optional[Path],
    playlists: tuple[str, ...],
    target_dir: Optional[Path],
    workers: Optional[int],
    dry_run: bool,
    keep_temp: bool,
    yes: bool,
    ffmpeg_backend: str,
):
    """Transcode and transfer one or more clusters to a device."""
    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    with Session(engine, future=True) as session:
        profile = _load_profile(session, profile_name, profile_dir)
        tracks = _collect_tracks_for_playlists(session, playlists)
        if not tracks:
            click.echo("No tracks to transfer.")
            return

        plan_obj = _plan(tracks, profile)
        click.echo(
            f"Plan: bitrate={plan_obj.bitrate_kbps} kept={len(plan_obj.kept)} "
            f"dropped={len(plan_obj.dropped)} bytes={plan_obj.total_kept_bytes}"
        )
        if plan_obj.warnings:
            for w in plan_obj.warnings:
                click.echo(f"  warning: {w}")
        if plan_obj.dropped and not yes and not dry_run:
            for d in plan_obj.dropped[:10]:
                click.echo(f"  drop: track_id={d.track_id} {d.source_path}")
            if len(plan_obj.dropped) > 10:
                click.echo(f"  …and {len(plan_obj.dropped) - 10} more")
            click.confirm("Proceed with dropping these tracks?", abort=True)

        if dry_run:
            return

        target_root = target_dir or (Path(profile.mount_hint) if profile.mount_hint else None)
        if target_root is None:
            raise click.UsageError("--target-dir required (profile has no mount_hint)")
        target_root.mkdir(parents=True, exist_ok=True)
        target = LocalDirectoryTarget(target_root)
        runner = _build_ffmpeg_runner(ffmpeg_backend)

        playlist_name = playlists[0] if len(playlists) == 1 else "combined"
        m3u_relpath = _PurePath("Playlists") / f"{playlist_name}.m3u"
        outcome = transfer_mod.execute_transfer(
            session=session,
            profile=profile,
            plan=plan_obj,
            target=target,
            ffmpeg=runner,
            m3u_relpath=m3u_relpath,
            cache_dir=paths_mod.cache_dir() / "transcode",
            workers=workers or 1,
            keep_temp=keep_temp,
        )
    click.echo(
        f"Transfer done: copied={outcome.copied} skipped={outcome.skipped} "
        f"failed={outcome.failed}"
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add transfer subcommand (planner + transcode + copy + m3u)"
```

---

## Task 11: README update for Phase 3

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README**

Overwrite `README.md`:

```markdown
# audio-tools

Linux desktop music manager: mood/tempo-based playlist clustering + size-optimized media-player transfer.

**Status:** Phase 3 (transfer). Phase 4 (GUI) pending.

## Requirements

- Python 3.11+
- `ffmpeg` (transcoding + fixture generation)
- `sqlite3` (optional)
- `essentia-tensorflow` (optional, install via `pip install -e ".[analysis]"`)

## Install (development)

```bash
git clone <repo> audio-tools
cd audio-tools
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[dev,analysis]"   # opt-in Essentia
alembic upgrade head
```

## CLI

```bash
audio-tools scan ~/Music
audio-tools fetch-models                   # download Essentia TF models
audio-tools analyze                        # feature extraction
audio-tools cluster --k 6
audio-tools playlists                      # write per-cluster m3u files

# Transfer
audio-tools transfer --profile walkman --playlist Workout \
                     --target-dir /run/media/$USER/WALKMAN [--dry-run]
```

`transfer` runs the bitrate planner against the chosen device profile, drops tail tracks if even the minimum bitrate can't fit, transcodes via ffmpeg (or skips with codec=copy), preserves album art (passthrough for mp3/m4a, mutagen post-embed for opus), and copies into the device's `folder_layout`. An m3u with `m3u_path_style` paths is written under `Playlists/`. A `transfer_sessions` row is written for each run; rsync-style sha1 matching skips unchanged files on re-runs.

## Tests

```bash
pytest -v
```

Golden tests under `tests/golden/` use real ffmpeg / Essentia and are auto-skipped when absent.

## Design docs

- Parent spec: [`docs/superpowers/specs/2026-05-25-audio-tools-design.md`](docs/superpowers/specs/2026-05-25-audio-tools-design.md)
- Phase 1 plan: [`docs/superpowers/plans/2026-05-25-audio-tools-phase1-foundation.md`](docs/superpowers/plans/2026-05-25-audio-tools-phase1-foundation.md)
- Phase 2 design / plan: `docs/superpowers/specs/2026-05-26-audio-tools-phase2-design.md` / `docs/superpowers/plans/2026-05-26-audio-tools-phase2-analyzer-clusterer-playlists.md`
- Phase 3 design / plan: `docs/superpowers/specs/2026-05-26-audio-tools-phase3-design.md` / `docs/superpowers/plans/2026-05-26-audio-tools-phase3-transfer.md`
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest -v
```
Expected: full suite green; golden tests pass or skip.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for Phase 3 (transfer)"
```

---

## Phase 3 Completion Checklist

- [ ] `pytest -v` reports 100% pass (golden tests pass or SKIP)
- [ ] `audio-tools transfer --profile walkman --playlist Workout --target-dir /tmp/usb --dry-run` prints a plan summary without touching the target
- [ ] `audio-tools transfer ... --yes` with `AUDIO_TOOLS_ALLOW_FAKE_FFMPEG=1` writes files under `<target>/<folder_layout>/...` and an m3u under `<target>/Playlists/`
- [ ] Re-running the same transfer reports `skipped=N` and leaves the target byte-identical
- [ ] `transfer_sessions` row exists with `status='completed'`, `bitrate_kbps`, `kept_count`, `dropped_count` populated
- [ ] `alembic upgrade head` from a fresh DB applies 0001 → 0005 cleanly

When all checked: Phase 3 is done. Phase 4 (GUI) next.
