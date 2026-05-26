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
