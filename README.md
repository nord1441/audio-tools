# audio-tools

Linux desktop music manager focused on mood/tempo-based playlist clustering and size-optimized media player transfer.

**Status:** Phase 1 (foundation). CLI scan works; analysis, clustering, transfer, and GUI are forthcoming.

## Requirements

- Python 3.11+
- `ffmpeg` (for fixture generation in tests; will be required for transcoding in Phase 3)
- `sqlite3` (only for inspecting the DB manually)

## Install (development)

```bash
git clone <repo> audio-tools
cd audio-tools
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head        # create/migrate the SQLite database
```

## Run

```bash
audio-tools --version
audio-tools scan ~/Music
```

`scan` walks the directory and records every supported audio file (`.mp3 .flac .ogg .opus .m4a .wav`) in `~/.local/share/audio-tools/audio_tools.db` (XDG). Subsequent scans only process changes (new, modified, moved, or removed files).

## Tests

```bash
pytest -v
```

Audio fixtures are generated on first run via `tests/fixtures/generate_audio_fixtures.sh` (requires `ffmpeg`).

## Design docs

- Spec: [`docs/superpowers/specs/2026-05-25-audio-tools-design.md`](docs/superpowers/specs/2026-05-25-audio-tools-design.md)
- Phase 1 plan: [`docs/superpowers/plans/2026-05-25-audio-tools-phase1-foundation.md`](docs/superpowers/plans/2026-05-25-audio-tools-phase1-foundation.md)
