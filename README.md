# audio-tools

Linux desktop music manager: mood/tempo-based playlist clustering + size-optimized media-player transfer + PySide6 GUI.

**Status:** Phase 4 (GUI MVP). All four pipeline phases complete (scan → analyze → cluster → playlist → transfer).

## Requirements

- Python 3.11+
- `ffmpeg`
- `essentia-tensorflow` (optional, install via `pip install -e ".[analysis]"`)
- `PySide6` (optional, install via `pip install -e ".[gui]"`)

## Install (development)

```bash
git clone <repo> audio-tools
cd audio-tools
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"                  # core only
pip install -e ".[dev,analysis,gui]"     # full stack
alembic upgrade head
```

## CLI

```bash
audio-tools scan ~/Music
audio-tools fetch-models
audio-tools analyze
audio-tools cluster --k 6
audio-tools playlists
audio-tools transfer --profile walkman --playlist Workout --target-dir /run/media/$USER/WALKMAN
audio-tools gui                          # PySide6 desktop
```

## Tests

```bash
pytest -v                                # all
pytest tests/unit tests/golden -v        # CLI tests only (no Qt)
QT_QPA_PLATFORM=offscreen pytest tests/gui -v   # GUI smoke
```

`tests/golden/` uses real ffmpeg / Essentia and skips when those are missing. `tests/gui/` skips when PySide6 is missing.

## Design docs

- Parent spec: `docs/superpowers/specs/2026-05-25-audio-tools-design.md`
- Per-phase plans and addenda: see `docs/superpowers/plans/` and `docs/superpowers/specs/`.
