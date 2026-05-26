# audio-tools Phase 3 (TransferPlanner + Transcoder + Transfer Execution) Design Addendum

**Date**: 2026-05-26
**Status**: Approved
**Parent spec**: [`2026-05-25-audio-tools-design.md`](./2026-05-25-audio-tools-design.md)

Phase 3 implements §8 (Device Profile + Transfer Logic) of the parent spec. This addendum captures Phase-3-specific implementation choices.

## Scope

Implement, with CLI surfaces:
- `TransferPlanner` (pure-Python) computing kept/dropped tracks at the optimal bitrate for a given device.
- `Transcoder` (ffmpeg subprocess wrapper) producing files matching the profile's codec/bitrate.
- Album art preservation per codec (passthrough for mp3/m4a, mutagen post-embed for opus).
- `LocalDirectoryTarget` covering both USB mounts and gvfs MTP paths (which appear as local directories under `/run/user/$UID/gvfs/`).
- `transfer_sessions` row per run + rsync-style sha1 skip for resume.
- `audio-tools transfer` CLI.

Out of scope:
- A dedicated `MTPTarget` using `libmtp`/`gvfs` system calls. Phase 3 relies on the gvfs FUSE layer presenting MTP devices as ordinary directories. If the FUSE coverage proves insufficient on a target device, a Phase 3.5 follow-up will add a real MTP backend behind the same `TransferTarget` protocol.
- GUI for transfer progress (Phase 4).
- Parallel m3u writing (transfers are CPU-bound on ffmpeg; m3u write is trivial and runs at the end of the session).

## Module Layout

```
src/audio_tools/core/
  transfer_target.py       # TransferTarget protocol + LocalDirectoryTarget
  transcoder.py            # FfmpegRunner protocol + RealFfmpegRunner + FakeFfmpegRunner + transcode driver
  transfer_planner.py      # plan() — pure-Python bitrate + drop search
  album_art.py             # preserve_album_art(src, dst, codec)
  transfer.py              # execute() — orchestrates transcode + copy + m3u + session
  models.py                # +TransferSession

alembic/versions/
  0005_create_transfer_sessions.py

src/audio_tools/
  cli.py                   # +transfer subcommand
```

**Responsibility boundaries (strict):**
- `transfer_planner.py` — feature/track rows + profile → plan object. No I/O.
- `transcoder.py` — single-file transcode + batch driver. Talks only to `FfmpegRunner`.
- `album_art.py` — only image preservation logic. Used by `transfer.py`, not by `transcoder.py` directly.
- `transfer_target.py` — abstract filesystem destination. No business logic.
- `transfer.py` — wires the four above + DB session writes.
- `cli.py` — argument parsing and wiring.

## Data Model (additions)

```
transfer_sessions
  id                    INTEGER PK
  profile_id            INTEGER FK → device_profiles.id
  started_at            DATETIME NOT NULL
  finished_at           DATETIME NULL
  status                TEXT NOT NULL          -- 'running' | 'completed' | 'aborted' | 'failed'
  bytes_transferred     INTEGER NOT NULL DEFAULT 0
  bitrate_kbps          INTEGER NULL           -- the bitrate the planner settled on
  kept_count            INTEGER NOT NULL DEFAULT 0
  dropped_count         INTEGER NOT NULL DEFAULT 0
  error                 TEXT NULL              -- last-error message when status='failed'/'aborted'
```

No new indices in Phase 3 (sessions table will stay small).

## TransferPlanner

Pure-Python. No DB writes, no file I/O. Input: a list of `Track` records and an in-memory `DeviceProfile` snapshot. Output: a `TransferPlan` dataclass.

```python
@dataclass(frozen=True)
class PlannedTrack:
    track_id: int
    source_path: Path
    output_size_bytes: int      # predicted size at the chosen bitrate
    codec: str                  # 'opus'|'mp3'|'aac'|'copy'
    bitrate_kbps: int           # 0 when codec='copy'

@dataclass(frozen=True)
class TransferPlan:
    bitrate_kbps: int           # chosen bitrate (or 0 if codec='copy')
    kept: list[PlannedTrack]
    dropped: list[PlannedTrack]
    total_kept_bytes: int
```

### Size prediction

```
predict_size(track, codec, bitrate_kbps) -> int
  if codec == 'copy':
      return track.size
  bits = track.duration_s * bitrate_kbps * 1000
  return int(bits / 8 * 1.05)  # 5% safety margin
```

When `track.duration_s` is `None`, fall back to source size and the planner emits a warning string included in the plan (CLI prints it).

### Search algorithm

Spec §8 verbatim. Implemented as a single function:

```python
def plan(tracks: list[Track], profile: DeviceProfile) -> TransferPlan
```

Steps:
1. Validate input: `min_bitrate <= max_bitrate`, `bitrate_step > 0`. Raise `TransferPlanError` on bad input.
2. If `codec == 'copy'`: total = sum(track.size); skip the bitrate search; jump to dropping.
3. Otherwise: for bitrate in `range(max_bitrate, min_bitrate - 1, -bitrate_step)` plus `min_bitrate` as the final tail: compute total; first that fits is kept.
4. If still over capacity at `min_bitrate` (or `copy`): drop from the tail according to the `tracks` input order (caller is responsible for sorting per playlist ordering rules).
5. Pack and return.

### Multi-playlist ordering

The planner does **not** know about playlists. Multi-playlist ordering is the caller's responsibility (CLI builds the list by interleaving/concatenating per the spec's priority rules).

### Tests

Pure-Python; ≥10 cases covering:
- Fits at max bitrate, no drops.
- Drops needed, drops correct tail.
- Codec=`copy`, fits.
- Codec=`copy`, drops required.
- Tracks with `duration_s=None` (size fallback).
- Empty input → empty plan.
- Single track over capacity → plan is empty + dropped=[that track].
- `min_bitrate > max_bitrate` → `TransferPlanError`.

## Transcoder

### FfmpegRunner protocol

```python
class FfmpegRunner(Protocol):
    def run(self, args: list[str]) -> CompletedProcess: ...
```

Implementations:
- `RealFfmpegRunner`: thin `subprocess.run(["ffmpeg", *args], check=False, capture_output=True)` wrapper.
- `FakeFfmpegRunner`: invoked by tests. Default behavior copies `args[args.index('-i') + 1]` to the `-c …` output path, ignoring codec/bitrate, returning rc=0. Tests may override behavior per-instance.

### transcode() — single file

```python
def transcode(
    runner: FfmpegRunner,
    src: Path,
    dst: Path,
    *,
    codec: str,               # 'opus'|'mp3'|'aac'|'copy'
    bitrate_kbps: int,
    sample_rate_max: int,
) -> None
```

Builds the ffmpeg argv per codec (see table below), invokes `runner.run()`, and on `returncode != 0` raises `TranscodeError(rc, stderr)`. For `copy`, the function shells out to `shutil.copyfile`, **not** ffmpeg — the codec='copy' path skips ffmpeg entirely.

| Codec | ffmpeg args (skeleton) |
|---|---|
| opus | `-vn -c:a libopus -b:a {bitrate}k -ar {min(48000, src_rate, sample_rate_max)} -ac 2` |
| mp3 | `-map 0:a -map 0:v? -c:v copy -c:a libmp3lame -b:a {bitrate}k -id3v2_version 3 -write_id3v1 0` |
| aac | `-map 0:a -map 0:v? -c:v copy -c:a aac -b:a {bitrate}k -movflags +faststart` |

Each invocation includes `-y -hide_banner -loglevel error -i {src} {extra} {dst}`.

### batch_transcode()

```python
def batch_transcode(
    runner: FfmpegRunner,
    items: Iterable[TranscodeItem],
    *,
    workers: int = os.cpu_count(),
) -> Iterator[TranscodeOutcome]
```

Submits each item to a `ThreadPoolExecutor`. Each thread invokes `transcode()` which spawns one ffmpeg subprocess. The outcome yields `(track_id, ok|err)` as work completes. ThreadPool (not ProcessPool) because ffmpeg already provides process isolation and threads carry less overhead.

### Tests

- Unit (FakeFfmpegRunner): batch ordering, error handling on rc != 0, codec arg construction (assert exact argv).
- Golden (real ffmpeg, skipped if missing): convert a 2-second tagged mp3 fixture to each output codec, assert output file exists, has the right extension, and mutagen reports the expected codec.

## Album Art

Module `core/album_art.py`. Single public function:

```python
def preserve_album_art(src: Path, dst: Path, codec: str) -> bool
```

Returns `True` if an image was preserved, `False` otherwise.

Behavior per output codec:
- `mp3`, `aac`: rely on the transcoder's `-map 0:v?` clause to passthrough the image stream. `preserve_album_art` for these codecs reads `dst` with mutagen and asserts a picture is present; logs a warning if not.
- `opus`: extract the picture from `src` using mutagen, re-encode to JPEG if not already PNG/JPEG (via Pillow — added as a dependency), then write it into `dst`'s `METADATA_BLOCK_PICTURE` Vorbis comment.
- `copy`: no-op (the file already has whatever art it had).

If `src` has no picture, the function is a no-op and returns `False`.

### Tests

Golden tests in `tests/golden/test_album_art.py`. Each codec: produce a tagged fixture with a known JPEG → transcode → run `preserve_album_art` → assert mutagen finds a picture of the right type. Skipped if `Pillow` or `ffmpeg` is missing.

## TransferTarget

### Protocol

```python
class TransferTarget(Protocol):
    def exists(self, relpath: PurePath) -> bool: ...
    def file_sha1(self, relpath: PurePath) -> str | None: ...
    def available_bytes(self) -> int: ...
    def copy_file(self, src: Path, relpath: PurePath) -> None: ...
    def remove(self, relpath: PurePath) -> None: ...
    def write_text(self, relpath: PurePath, text: str) -> None: ...
```

Paths exposed to the protocol are always device-relative (`PurePath`); the target resolves them against its root.

### LocalDirectoryTarget

```python
LocalDirectoryTarget(root: Path)
```

Validates `root.is_dir()` at construction. All protocol methods route through `root / relpath`. `available_bytes()` calls `shutil.disk_usage(root).free`.

`file_sha1()` computes the hex digest using the same 1 MiB chunked loop as `core/scanner.sha1_of`. We factor that helper out of `scanner.py` into a new `core/hashing.py` so both modules share it (small refactor included in the Phase 3 plan as Task 1).

### Why LocalDirectoryTarget covers MTP

gvfs mounts MTP devices at paths like `/run/user/1000/gvfs/mtp:host=…/Internal shared storage/Music`. From userspace, these read and write as ordinary directories. Performance is poor (no `mmap`, no `rename`), but functional. Phase 3 accepts this performance for the win of a single transfer code path.

If a Phase-3.5 MTPTarget arrives, it implements the same protocol and `cli.py` chooses by `--target-dir=mtp://…` URL syntax, similar to how `AUDIO_TOOLS_DB_URL` works today.

## Transfer Orchestration

```python
def execute_transfer(
    *,
    session: Session,
    profile: DeviceProfile,
    plan: TransferPlan,
    target: TransferTarget,
    ffmpeg: FfmpegRunner,
    workers: int = os.cpu_count(),
    cache_dir: Path = paths.cache_dir() / "transcode",
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> TransferOutcome
```

### Order of operations

1. Insert `transfer_sessions` row with `status='running'`, `bitrate_kbps=plan.bitrate_kbps`, `kept_count`, `dropped_count`. Commit. Remember its id.
2. Install a SIGINT handler that flips a `_aborted` flag, calls `_finalize(status='aborted')` and re-raises.
3. For each `PlannedTrack` in `plan.kept`:
   a. Compute target relpath from `profile.folder_layout` (Python format-string substitution against the track's title/artist/album/track-number from tags).
   b. Compute staged path in `cache_dir / f"{track_id}.{ext}"`.
   c. If `target.exists(relpath)`: compare hashes. If `target.file_sha1(relpath)` equals `expected_sha1` of the staged-but-not-yet-existing file — we don't know that yet! So actually: transcode first, then compute its sha1, then check whether the device already has the same hash. (Simpler, still safe.)
   d. Submit `transcode(...)` via `batch_transcode`'s `ThreadPoolExecutor`. (Implementation note: structure as collect-then-iter rather than streaming; `execute_transfer` is fine to keep blocking semantics with periodic progress callbacks.)
   e. After successful transcode: if a picture should be embedded (opus path), call `album_art.preserve_album_art`. Compute staged sha1.
   f. If `target.file_sha1(relpath) == staged_sha1`: skip the copy (rsync-style). Else `target.copy_file(staged, relpath)` and update `transfer_sessions.bytes_transferred`.
   g. Emit progress event.
4. After all transcodes: write the m3u(s) to the target via `target.write_text`, with paths rewritten per `profile.m3u_path_style`.
5. Update `transfer_sessions` row → `status='completed'`, `finished_at=now`.
6. Restore signal handler.
7. Clean `cache_dir` unless `keep_temp=True`.

### Error handling

- A single-track transcode failure does not abort the session — it logs into a per-session error list and continues (`status='completed'` at end; failed tracks are not in the m3u). If more than 50% of tracks fail, `status='failed'`.
- `IOError`/`OSError` from `target.copy_file` (e.g., device removed mid-flight): immediately `status='aborted'`, signal handler-style cleanup.
- Ctrl-C: handled per spec — session marked `aborted`, partial files (current in-flight copy) removed via `target.remove`.

### Resume

Re-running `audio-tools transfer` with the same profile + playlist set:
1. Queries `transfer_sessions` for the most recent `status='aborted'` matching profile. If found: prints a one-liner "resuming session id=N (aborted at bytes_transferred=…)".
2. Runs the same planner pass (deterministic, same inputs).
3. For each `PlannedTrack`: the existence + sha1 skip path naturally handles already-transferred files.
4. Opens a fresh `transfer_sessions` row for this run (does NOT mutate the prior session).

## Output staging

`cache_dir` defaults to `paths.cache_dir() / "transcode"`. Each track gets a unique staged filename (`f"{track_id}.{ext}"`). On `keep_temp=False` we delete the cache_dir subtree on success; on abort we leave it for inspection.

## CLI

```
audio-tools transfer --profile NAME [--profile-dir PATH]
                     --playlist NAME [--playlist NAME...]
                     [--target-dir PATH]
                     [--workers N]
                     [--dry-run]
                     [--keep-temp]
                     [--yes]                  # skip the "X tracks dropped — continue?" prompt
```

- `--profile`: looks up `DeviceProfile` row by name. If the row doesn't exist, the CLI loads `--profile-dir/<name>.yaml` (default: XDG `devices/`) via the Phase 1 loader.
- `--playlist`: cluster name (must match `Cluster.name`). Repeating accumulates.
- `--target-dir`: overrides `profile.mount_hint`. Required if `mount_hint` is null. Must be an existing directory.
- `--workers`: defaults to `os.cpu_count()`.
- `--dry-run`: runs the planner, prints `bitrate=N kept=M dropped=K bytes=B`, lists the first 10 dropped tracks if any, exits without touching the target.
- `--keep-temp`: leaves staged transcodes for inspection.
- `--yes`: skip the interactive drop confirmation.

## Testing strategy

| Layer | Backend | What it asserts |
|---|---|---|
| TransferPlanner unit | pure-Python | ≥10 cases as listed above |
| Transcoder unit | FakeFfmpegRunner | argv per codec; batch_transcode ordering; error mapping |
| Transcoder golden | RealFfmpegRunner | each codec produces a playable file (mutagen re-read) |
| LocalDirectoryTarget unit | tmp_path | exists/copy_file/sha1/available_bytes round-trip |
| AlbumArt golden | Real ffmpeg + Pillow | each codec preserves an embedded picture |
| Transfer execute unit | FakeFfmpegRunner + LocalDirectoryTarget | session lifecycle, skip-existing path, Ctrl-C handling, partial-failure threshold |
| CLI integration | FakeFfmpegRunner + LocalDirectoryTarget | end-to-end transfer to a tmp dir |

CI runs the unit + CLI tests. Golden tests skip on missing ffmpeg/Pillow.

## Acceptance for Phase 3

- `audio-tools transfer --profile walkman --playlist Workout --target-dir /tmp/usb --dry-run` prints the plan without touching the target.
- `audio-tools transfer --profile walkman --playlist Workout --target-dir /tmp/usb --yes` produces transcoded files in `/tmp/usb/<folder_layout>/...`, an m3u with the configured `m3u_path_style`, and a `transfer_sessions` row with `status='completed'`.
- Re-running the same transfer reports `skipped=N` and leaves `/tmp/usb` byte-identical.
- Killing the process with SIGINT mid-transfer leaves `transfer_sessions.status='aborted'` and no stray `.part` files on the target.
- All previous Phase 1 + 2 tests still pass; Phase 3 unit suite adds ≥25 tests and stays <3s.
