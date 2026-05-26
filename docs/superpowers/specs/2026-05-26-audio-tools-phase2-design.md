# audio-tools Phase 2 (Analyzer + Clusterer + PlaylistBuilder) Design Addendum

**Date**: 2026-05-26
**Status**: Approved
**Parent spec**: [`2026-05-25-audio-tools-design.md`](./2026-05-25-audio-tools-design.md)

Phase 2 implements §6 (Analysis Pipeline) and §7 (Clustering and Playlist Generation) of the parent spec. This addendum captures Phase-2-specific implementation choices that the parent spec leaves open.

## Scope

Implement, with CLI surfaces:
- Local feature extraction via Essentia + TensorFlow models (BPM, key, energy, danceability, mood_happy/sad/aggressive/relaxed, loudness, spectral_centroid, MusiCNN embedding).
- k-means clustering with both full re-fit and incremental nearest-centroid assignment.
- Per-cluster m3u playlist generation (absolute paths, EXTM3U + EXTINF).

Out of scope for Phase 2:
- GUI (Phase 4).
- Auto-trigger for incremental clustering on ≥50 new tracks — Phase 2 ships explicit commands only.
- Cluster rename via CLI — clusters get an auto-name (`Cluster {n}`); renaming is Phase 4 / GUI.
- Elbow-method plotting — Phase 4 / GUI.
- Transfer-time path style — Phase 3.

## Module Layout

```
src/audio_tools/core/
  analyzer.py            # AnalyzerBackend protocol, EssentiaBackend, FakeBackend, analyze() driver
  clusterer.py           # recluster(), assign_new()
  playlist_builder.py    # write_playlists()
  models.py              # +Features, +Cluster, +ClusterAssignment

alembic/versions/
  0003_create_features.py
  0004_create_clusters.py

src/audio_tools/
  cli.py                 # +fetch-models, +analyze, +cluster, +playlists subcommands
```

**Responsibility boundaries (strict):**
- `analyzer.py`: track row → features row. No clustering, no filesystem walk (Scanner already populated `tracks`).
- `clusterer.py`: features → clusters + cluster_assignments. Pure numpy/sklearn; never reads or writes audio files.
- `playlist_builder.py`: cluster_assignments + track paths → m3u files. No DB writes.
- `cli.py`: wiring only.

## Data Model (additions)

```
features
  track_id            INTEGER PK/FK → tracks.id
  bpm                 REAL
  key                 TEXT          -- e.g., "C", "F#"
  scale               TEXT          -- "major" | "minor"
  energy              REAL
  danceability        REAL
  mood_happy          REAL
  mood_sad            REAL
  mood_aggressive     REAL
  mood_relaxed        REAL
  loudness            REAL
  spectral_centroid   REAL
  embedding           BLOB          -- numpy float32, 200-dim MusiCNN; stored as raw bytes
  analyzed_at         DATETIME      -- when this row was written

clusters
  id                  INTEGER PK
  name                TEXT          -- defaults to "Cluster {id}", user-renamable later
  color               TEXT NULL     -- hex string set in GUI, NULL until then
  k_value             INTEGER       -- the k used at creation
  centroid            BLOB          -- float32, 200-dim
  created_at          DATETIME

cluster_assignments
  track_id            INTEGER PK/FK → tracks.id
  cluster_id          INTEGER FK → clusters.id  -- INDEX
  distance            REAL          -- L2 distance to centroid at assignment time
  assigned_at         DATETIME
```

Indices: `cluster_assignments.cluster_id` (lookup-by-cluster), `cluster_assignments.track_id` is PK.

## Analyzer

### Backend protocol

```python
class AnalyzerBackend(Protocol):
    def analyze(self, path: Path) -> FeatureDict: ...
    # Raises AnalyzeError on unrecoverable failure
    # Raises AnalyzeTimeout if internal timeout fires
```

Two implementations:
- **`EssentiaBackend`** — wraps Essentia's `MusicExtractor` (low-level features) + TF models (mood, MusiCNN embedding). Constructor takes the models dir; raises if required model files missing.
- **`FakeBackend`** — deterministic per-path features (e.g., hash-derived) for unit tests. No Essentia import.

### Driver

```python
def analyze_tracks(
    session: Session,
    backend: AnalyzerBackend,
    *,
    workers: int = os.cpu_count(),
    timeout_s: int = 300,
    rescan: bool = False,
) -> AnalyzeResult
```

- Selects tracks needing analysis: `LEFT JOIN features` with `features.track_id IS NULL` OR `rescan=True`.
- Submits each `(track_id, path)` to a `ProcessPoolExecutor`. Worker function imports the backend lazily inside the subprocess and calls `backend.analyze(path)`.
- Per-future `future.result(timeout=timeout_s)`. On `TimeoutError` or `AnalyzeError`, writes `tracks.last_analysis_error` with the failure reason and skips the features row.
- On success, UPSERTs the features row (PK = track_id, full row replace).
- Returns `AnalyzeResult(analyzed=N, skipped=N, failed=N)`.

The `FakeBackend` pathway runs in-process (no pool) to keep unit tests fast and debuggable; a `single_threaded=True` flag enables that.

### TF models

Models live in `~/.cache/audio-tools/models/` (resolved via `paths.models_dir()`, new helper in Task 2 of Phase 2 plan). Required files (Essentia's published URLs, hard-coded):
- `msd-musicnn-1.pb` (MusiCNN embedding)
- `mood_happy-msd-musicnn-1.pb`
- `mood_sad-msd-musicnn-1.pb`
- `mood_aggressive-msd-musicnn-1.pb`
- `mood_relaxed-msd-musicnn-1.pb`

`audio-tools fetch-models` downloads them with `requests` (or `urllib`), verifies SHA256 against pinned constants, and writes them atomically. Re-running is a no-op when files already exist with the correct hash.

## Clusterer

### `recluster(session, k: int)` — full re-fit
1. Read all `(track_id, embedding)` from `features`.
2. Stack into `np.ndarray` of shape `(n, 200)`, dtype float32.
3. Fit `sklearn.cluster.KMeans(n_clusters=k, random_state=42, n_init=10)`.
4. Delete existing rows in `clusters` and `cluster_assignments` (full rebuild).
5. Insert k new `clusters` rows with `centroid = float32 bytes of cluster_centers_[i]`, `name="Cluster {i+1}"`, `k_value=k`.
6. Insert `cluster_assignments` rows mapping each track to its assigned cluster, with `distance = ||embedding - centroid||_2`.

### `assign_new(session)` — incremental
1. Find features rows that have no `cluster_assignments` row.
2. If no existing clusters, raise `ClusterError("no clusters; run cluster --k N first")`.
3. Load existing centroids into an `(k, 200)` array.
4. For each new embedding, compute argmin L2 distance to centroids.
5. INSERT into `cluster_assignments`.
6. Existing assignments are **never** modified — user-visible cluster identity is stable.

### Behavior when clusters already exist
`audio-tools cluster` with no args:
- If `clusters` is empty → full re-fit with `k=6`.
- Otherwise → `assign_new()`.

`audio-tools cluster --k N` always forces a full re-fit at the given k (interactive prompt: "this will reset all cluster assignments — continue? [y/N]" unless `--force`).

## PlaylistBuilder

`write_playlists(session, out_dir: Path) -> list[Path]`:
- For each cluster, query its assigned tracks ordered by `distance ASC` (nearest-to-centroid first — gives the most "central" examples at the top).
- Filename: sanitize cluster name to `[A-Za-z0-9._-]`, collapse runs to `_`, fall back to `cluster_{id}` if empty after sanitization. Append `.m3u`.
- Content: EXTM3U header, one `#EXTINF:duration,artist - title` line + absolute path per track.
- `out_dir` defaults to `paths.playlists_dir()`.
- Returns the list of written paths. Pre-existing m3u files in the dir are overwritten only if they match a current cluster name; orphans (e.g., from a previous larger k) are left in place (caller's responsibility to clean if desired) — this is the conservative choice.

## CLI Surfaces

```
audio-tools fetch-models                            # downloads TF models into XDG cache
audio-tools analyze [--backend=fake|essentia]       # default essentia
                    [--rescan]                       # recompute even if features exist
                    [--workers=N] [--timeout=SEC]
audio-tools cluster [--k=N] [--incremental] [--force]
audio-tools playlists [--out-dir=PATH]              # default XDG playlists dir
```

`--backend=fake` is honored only when AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1 is set, to prevent accidental real-world use.

## Testing

- **Unit (FakeBackend pathway):** Analyzer UPSERT idempotency, `rescan` behavior, timeout handling (Fake variant that raises `AnalyzeTimeout`), error recording on `AnalyzeError`, worker count plumbing.
- **Unit (Clusterer):** synthetic embeddings constructed from k well-separated Gaussian blobs → assert recluster groups them correctly. `assign_new` against fixed centroids.
- **Unit (PlaylistBuilder):** golden-string m3u comparison (header + one track), filename sanitization edge cases, empty-cluster handling.
- **Golden integration:** one test that uses real Essentia on `tests/fixtures/audio/test_tagged.mp3` and asserts `100 < bpm < 200` and key in the 24-element key set. Marked `pytest.mark.skipif(not _essentia_available())`.

CI does not install Essentia (out of scope for Phase 2); the golden test is dev-machine-local. Unit suite must stay <2s.

## Acceptance

- `audio-tools fetch-models` downloads all 5 model files, verifies SHA256, idempotent on re-run.
- `audio-tools analyze ~/Music --backend=fake` (with `AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1`) produces one features row per scanned track, exits 0.
- `audio-tools analyze ~/Music` (real Essentia, models installed) writes plausible BPM/key/mood for ≥1 real audio file; pathological files surface in `tracks.last_analysis_error` without aborting the run.
- `audio-tools cluster --k 4` produces 4 clusters and assignments; `audio-tools cluster` afterwards is a no-op if no new features were added.
- `audio-tools playlists` writes one m3u per cluster; each is parseable EXTM3U and contains absolute paths.
- All previous Phase 1 tests still pass; Phase 2 unit suite adds ≥30 tests and stays <2s.
