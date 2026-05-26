# audio-tools

Linux desktop music manager focused on mood/tempo-based playlist clustering and size-optimized media player transfer.

**Status:** Phase 2 (analysis + clustering + playlist export). Phase 3 (transfer) and Phase 4 (GUI) pending.

## Requirements

- Python 3.11+
- `ffmpeg` (fixture generation; transcoding in Phase 3)
- `sqlite3` (optional, for manual DB inspection)
- `essentia-tensorflow` (optional, install via `pip install -e ".[analysis]"`)

## Install (development)

```bash
git clone <repo> audio-tools
cd audio-tools
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"                # core + tests (no Essentia)
# Optional: install Essentia for real analysis
pip install -e ".[dev,analysis]"
alembic upgrade head                   # create/migrate the SQLite database
```

## Run

```bash
audio-tools --version
audio-tools scan ~/Music               # discover audio files
audio-tools fetch-models               # download Essentia TF models into ~/.cache/audio-tools/models
audio-tools analyze                    # extract features (BPM, key, mood, MusiCNN embedding)
audio-tools cluster --k 6
audio-tools playlists                  # write per-cluster m3u files
```

- `scan` walks the directory, recording every supported audio file in `~/.local/share/audio-tools/audio_tools.db` (XDG). Incremental on subsequent runs.
- `analyze` extracts features for tracks that need (re-)analysis. `--backend=fake` produces deterministic synthetic features for testing (requires `AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1`). `--rescan` forces recomputation. Parallel via `ProcessPoolExecutor`.
- `cluster` runs k-means against the feature embeddings. With no flags: incremental nearest-centroid assignment if clusters exist; otherwise full re-fit with k=6.
- `playlists` writes one m3u per cluster into `~/.local/share/audio-tools/playlists/` (or `--out-dir=PATH`). Each playlist contains absolute paths sorted by distance-to-centroid (most representative first).

## Tests

```bash
pytest -v
```

Audio fixtures auto-generate on first run via `tests/fixtures/generate_audio_fixtures.sh` (requires `ffmpeg`). The `tests/golden/` suite uses real Essentia; it is automatically skipped when essentia isn't installed.

## Design docs

- Parent spec: [`docs/superpowers/specs/2026-05-25-audio-tools-design.md`](docs/superpowers/specs/2026-05-25-audio-tools-design.md)
- Phase 1 plan: [`docs/superpowers/plans/2026-05-25-audio-tools-phase1-foundation.md`](docs/superpowers/plans/2026-05-25-audio-tools-phase1-foundation.md)
- Phase 2 design: [`docs/superpowers/specs/2026-05-26-audio-tools-phase2-design.md`](docs/superpowers/specs/2026-05-26-audio-tools-phase2-design.md)
- Phase 2 plan: [`docs/superpowers/plans/2026-05-26-audio-tools-phase2-analyzer-clusterer-playlists.md`](docs/superpowers/plans/2026-05-26-audio-tools-phase2-analyzer-clusterer-playlists.md)
