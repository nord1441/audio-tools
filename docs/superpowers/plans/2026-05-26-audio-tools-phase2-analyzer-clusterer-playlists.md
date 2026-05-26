# audio-tools Phase 2 (Analyzer + Clusterer + PlaylistBuilder) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver local feature extraction (BPM/key/mood/MusiCNN embedding via Essentia+TF), k-means clustering of tracks, and per-cluster m3u playlist export. CLI grows `fetch-models`, `analyze`, `cluster`, `playlists`.

**Architecture:** `core/analyzer.py` introduces an `AnalyzerBackend` protocol with `EssentiaBackend` (real) and `FakeBackend` (test). Analyzer driver runs per-track work in `ProcessPoolExecutor` with a 5-minute timeout and writes a `features` row per track. `core/clusterer.py` reads embeddings and writes `clusters` / `cluster_assignments`. `core/playlist_builder.py` reads assignments and writes m3u files. CLI subcommands wire each step independently.

**Tech Stack:** Python 3.11+, scikit-learn (clustering), numpy (embeddings), requests (model download), essentia-tensorflow (real backend, optional extra), pytest. SQLAlchemy 2.0 + Alembic continue from Phase 1.

**Reference docs:**
- Parent spec: `docs/superpowers/specs/2026-05-25-audio-tools-design.md`
- Phase 2 spec addendum: `docs/superpowers/specs/2026-05-26-audio-tools-phase2-design.md`
- Phase 1 plan (for style reference): `docs/superpowers/plans/2026-05-25-audio-tools-phase1-foundation.md`

---

## File Structure (Phase 2)

```
audio-tools/
├── pyproject.toml                          # Task 1 (deps + analysis extra)
├── alembic/versions/
│   ├── 0003_create_features.py             # Task 3
│   └── 0004_create_clusters.py             # Task 4
├── src/audio_tools/
│   ├── paths.py                            # Task 1 (+models_dir)
│   ├── cli.py                              # Tasks 8, 10, 12, 14
│   └── core/
│       ├── models.py                       # Tasks 3, 4 (+Features, +Cluster, +ClusterAssignment)
│       ├── analyzer.py                     # Tasks 5–7 (built incrementally)
│       ├── clusterer.py                    # Tasks 9, 11
│       └── playlist_builder.py             # Task 13
└── tests/unit/
    ├── test_paths.py                       # Task 1 (+models_dir tests)
    ├── test_db.py                          # Tasks 3, 4 (+Features, +Cluster tests)
    ├── test_analyzer.py                    # Tasks 5–7
    ├── test_clusterer.py                   # Tasks 9, 11
    ├── test_playlist_builder.py            # Task 13
    └── test_cli.py                         # Tasks 8, 10, 12, 14
└── tests/golden/
    └── test_essentia_backend.py            # Task 7 (skipped if essentia missing)
```

**Responsibility boundaries:**
- `analyzer.py` — track row → features row only. No clustering, no filesystem walking (Scanner already populated `tracks`), no network.
- `clusterer.py` — features → clusters + cluster_assignments. Pure numpy/sklearn. Never reads audio files.
- `playlist_builder.py` — cluster_assignments + track paths → m3u files. No DB writes.
- `cli.py` — wiring only.

---

## Task 1: Phase 2 dependencies + `paths.models_dir()` helper

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/audio_tools/paths.py`
- Modify: `tests/unit/test_paths.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_paths.py`:

```python
def test_models_dir_under_xdg_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert paths.models_dir() == tmp_path / "audio-tools" / "models"


def test_ensure_dirs_creates_models_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    paths.ensure_dirs()
    assert paths.models_dir().is_dir()
```

- [ ] **Step 2: Verify failure**

```bash
source .venv/bin/activate
python -m pytest tests/unit/test_paths.py -v
```
Expected: FAIL (`AttributeError: module 'audio_tools.paths' has no attribute 'models_dir'`).

- [ ] **Step 3: Add `models_dir()` and `cache_dir()` to `paths.py`**

Replace the file (preserving existing helpers, adding the two new ones and threading `models_dir` into `ensure_dirs`):

```python
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

APP_NAME = "audio-tools"


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False))


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def cache_dir() -> Path:
    return Path(user_cache_dir(APP_NAME, appauthor=False))


def db_path() -> Path:
    return data_dir() / "audio_tools.db"


def device_profiles_dir() -> Path:
    return config_dir() / "devices"


def playlists_dir() -> Path:
    return data_dir() / "playlists"


def models_dir() -> Path:
    return cache_dir() / "models"


def ensure_dirs() -> None:
    for d in (
        config_dir(),
        data_dir(),
        cache_dir(),
        device_profiles_dir(),
        playlists_dir(),
        models_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Update `pyproject.toml` dependencies**

Modify `[project] dependencies` to add `scikit-learn`, `numpy`, and `requests`; add a new `[project.optional-dependencies] analysis` extra for `essentia-tensorflow`. Final shape:

```toml
[project]
name = "audio-tools"
version = "0.1.0"
description = "Mood/tempo-based music playlist generator and media player transfer tool"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "click>=8.1",
    "mutagen>=1.47",
    "pyyaml>=6.0",
    "platformdirs>=4.2",
    "numpy>=1.26",
    "scikit-learn>=1.4",
    "requests>=2.31",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.1",
]
analysis = [
    "essentia-tensorflow>=2.1b6.dev1110",
]
```

- [ ] **Step 5: Re-install and run tests**

```bash
pip install -e ".[dev]"
python -m pytest tests/unit/test_paths.py -v
```
Expected: all paths tests pass (8 total).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/audio_tools/paths.py tests/unit/test_paths.py
git commit -m "chore(phase2): add scikit-learn/numpy/requests deps and models_dir() helper"
```

---

## Task 2: Bring `tests/conftest.py` engine to file-based SQLite (foreign-keys aware)

The Phase 2 ORM relations need ON DELETE behavior to round-trip. The Phase 1 conftest creates a vanilla in-memory engine that does not honor SQLite `PRAGMA foreign_keys=ON`. Phase 1's `_enable_sqlite_wal` event handler in `core/db.py` does enable it, but only on connections produced by `make_engine`. We standardize the test fixture on `make_engine`.

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Replace `tests/conftest.py`**

```python
import pytest
from sqlalchemy.orm import Session

from audio_tools.core.db import Base, make_engine
from audio_tools.core import models  # noqa: F401  -- ensure models register


@pytest.fixture
def session(tmp_path):
    """File-backed SQLite session for unit tests (per-test fresh DB)."""
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        yield s
```

- [ ] **Step 2: Verify all prior tests still pass**

```bash
python -m pytest -v
```
Expected: all Phase 1 tests pass (file-backed engine is a drop-in replacement; the WAL/foreign-keys PRAGMAs are now applied uniformly).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: switch session fixture to make_engine for FK + WAL parity"
```

---

## Task 3: `Features` model + migration 0003

**Files:**
- Modify: `src/audio_tools/core/models.py`
- Create: `alembic/versions/0003_create_features.py`
- Modify: `tests/unit/test_db.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_db.py`:

```python
import numpy as np
from datetime import datetime

from audio_tools.core.models import Features


def test_features_insert_and_query(session):
    track = Track(path="/m/a.mp3", mtime=0.0, size=1)
    session.add(track)
    session.flush()  # populate id

    emb = np.arange(200, dtype=np.float32).tobytes()
    f = Features(
        track_id=track.id,
        bpm=128.0, key="C", scale="major",
        energy=0.7, danceability=0.6,
        mood_happy=0.5, mood_sad=0.1, mood_aggressive=0.2, mood_relaxed=0.4,
        loudness=-12.5, spectral_centroid=2500.0,
        embedding=emb,
        analyzed_at=datetime(2026, 5, 26, 12, 0, 0),
    )
    session.add(f)
    session.commit()

    fetched = session.get(Features, track.id)
    assert fetched.bpm == 128.0
    assert fetched.key == "C"
    assert len(fetched.embedding) == 200 * 4  # 200 float32s


def test_features_cascade_delete_when_track_deleted(session):
    track = Track(path="/m/x.mp3", mtime=0.0, size=1)
    session.add(track)
    session.flush()
    session.add(Features(track_id=track.id, embedding=b"\x00" * 800, analyzed_at=datetime.now()))
    session.commit()

    session.delete(track)
    session.commit()
    assert session.get(Features, track.id) is None
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_db.py -v
```
Expected: FAIL with `ImportError: cannot import name 'Features'`.

- [ ] **Step 3: Add `Features` to `src/audio_tools/core/models.py`**

Append (re-add `from datetime import datetime` and `LargeBinary` import at top if missing):

```python
from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text


class Features(Base):
    __tablename__ = "features"

    track_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    bpm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    scale: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    energy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    danceability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_happy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_sad: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_aggressive: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_relaxed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    loudness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spectral_centroid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

- [ ] **Step 4: Generate the migration**

```bash
rm -f /tmp/at_test_migration.db
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic upgrade head
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic revision --autogenerate -m "create features table" --rev-id 0003 --depends-on 0002
```

Inspect `alembic/versions/0003_create_features.py`. Confirm it contains exactly one `op.create_table('features', …)` with `sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='CASCADE')`. Trim any unrelated ops.

- [ ] **Step 5: Verify migration applies**

```bash
rm -f /tmp/at_test_migration.db
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic upgrade head
sqlite3 /tmp/at_test_migration.db ".schema features"
```
Expected schema shows all columns, PK on `track_id`, and the FK with `ON DELETE CASCADE`.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/unit/test_db.py -v
```
Expected: prior tests + 2 new tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/audio_tools/core/models.py alembic/versions/0003_create_features.py tests/unit/test_db.py
git commit -m "feat(db): add Features model and migration"
```

---

## Task 4: `Cluster` + `ClusterAssignment` models + migration 0004

**Files:**
- Modify: `src/audio_tools/core/models.py`
- Create: `alembic/versions/0004_create_clusters.py`
- Modify: `tests/unit/test_db.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_db.py`:

```python
from audio_tools.core.models import Cluster, ClusterAssignment


def test_cluster_and_assignment_roundtrip(session):
    track = Track(path="/m/c.mp3", mtime=0.0, size=1)
    session.add(track)
    session.flush()
    c = Cluster(
        name="Workout",
        k_value=4,
        centroid=b"\x00" * 800,
        created_at=datetime(2026, 5, 26, 12, 0, 0),
    )
    session.add(c)
    session.flush()
    session.add(ClusterAssignment(
        track_id=track.id,
        cluster_id=c.id,
        distance=0.42,
        assigned_at=datetime(2026, 5, 26, 12, 0, 0),
    ))
    session.commit()

    fetched = session.get(Cluster, c.id)
    assert fetched.name == "Workout"
    assert fetched.k_value == 4

    assignment = session.get(ClusterAssignment, track.id)
    assert assignment.cluster_id == c.id
    assert assignment.distance == 0.42


def test_assignment_cascades_when_track_deleted(session):
    track = Track(path="/m/d.mp3", mtime=0.0, size=1)
    session.add(track)
    session.flush()
    c = Cluster(name="X", k_value=2, centroid=b"\x00" * 800, created_at=datetime.now())
    session.add(c); session.flush()
    session.add(ClusterAssignment(
        track_id=track.id, cluster_id=c.id, distance=0.0, assigned_at=datetime.now()
    ))
    session.commit()

    session.delete(track)
    session.commit()
    assert session.get(ClusterAssignment, track.id) is None
    # Cluster row itself is untouched.
    assert session.get(Cluster, c.id) is not None
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_db.py -v
```
Expected: FAIL with `ImportError: cannot import name 'Cluster'`.

- [ ] **Step 3: Add models to `src/audio_tools/core/models.py`**

Append:

```python
class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    k_value: Mapped[int] = mapped_column(Integer, nullable=False)
    centroid: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ClusterAssignment(Base):
    __tablename__ = "cluster_assignments"

    track_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False
    )
    distance: Mapped[float] = mapped_column(Float, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_cluster_assignments_cluster_id", "cluster_id"),)
```

- [ ] **Step 4: Generate migration**

```bash
rm -f /tmp/at_test_migration.db
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic upgrade head
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic revision --autogenerate -m "create clusters and cluster_assignments" --rev-id 0004 --depends-on 0003
```

Inspect `alembic/versions/0004_create_clusters.py`. It should create both tables and the `ix_cluster_assignments_cluster_id` index. Trim any spurious ops.

- [ ] **Step 5: Verify migration applies**

```bash
rm -f /tmp/at_test_migration.db
AUDIO_TOOLS_DB_URL="sqlite:////tmp/at_test_migration.db" alembic upgrade head
sqlite3 /tmp/at_test_migration.db ".schema clusters"
sqlite3 /tmp/at_test_migration.db ".schema cluster_assignments"
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/unit/test_db.py -v
```
Expected: all DB tests pass (previous + 2 new).

- [ ] **Step 7: Commit**

```bash
git add src/audio_tools/core/models.py alembic/versions/0004_create_clusters.py tests/unit/test_db.py
git commit -m "feat(db): add Cluster and ClusterAssignment models with migration"
```

---

## Task 5: `AnalyzerBackend` protocol + `FakeBackend` + Analyzer driver (single-process)

**Files:**
- Create: `src/audio_tools/core/analyzer.py`
- Create: `tests/unit/test_analyzer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_analyzer.py`:

```python
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from audio_tools.core.analyzer import (
    AnalyzeError,
    AnalyzeResult,
    AnalyzeTimeout,
    FakeBackend,
    analyze_tracks,
)
from audio_tools.core.models import Features, Track


def _add_track(session, path: str, mtime: float = 1.0) -> Track:
    t = Track(path=path, mtime=mtime, size=1)
    session.add(t)
    session.commit()
    return t


def test_fake_backend_returns_deterministic_features(tmp_path):
    backend = FakeBackend()
    p = tmp_path / "a.mp3"
    p.write_bytes(b"x")
    out1 = backend.analyze(p)
    out2 = backend.analyze(p)
    assert out1 == out2
    assert isinstance(out1["embedding"], bytes)
    assert len(out1["embedding"]) == 200 * 4


def test_analyze_tracks_writes_features(tmp_path, session):
    _add_track(session, str(tmp_path / "a.mp3"))
    _add_track(session, str(tmp_path / "b.mp3"))

    result = analyze_tracks(session, FakeBackend(), single_threaded=True)
    assert isinstance(result, AnalyzeResult)
    assert result.analyzed == 2 and result.failed == 0

    rows = session.scalars(select(Features)).all()
    assert len(rows) == 2
    for r in rows:
        assert len(r.embedding) == 200 * 4
        assert r.analyzed_at is not None


def test_analyze_tracks_is_idempotent(tmp_path, session):
    _add_track(session, str(tmp_path / "a.mp3"))
    analyze_tracks(session, FakeBackend(), single_threaded=True)
    # Second call: nothing to do (features exist and mtime is unchanged)
    result = analyze_tracks(session, FakeBackend(), single_threaded=True)
    assert result.analyzed == 0


def test_analyze_tracks_redoes_when_track_mtime_newer(tmp_path, session):
    track = _add_track(session, str(tmp_path / "a.mp3"), mtime=100.0)
    analyze_tracks(session, FakeBackend(), single_threaded=True)
    # Touch: bump mtime past analyzed_at
    track.mtime = (datetime.utcnow() + timedelta(days=1)).timestamp()
    session.commit()

    result = analyze_tracks(session, FakeBackend(), single_threaded=True)
    assert result.analyzed == 1


def test_analyze_tracks_records_error(tmp_path, session):
    _add_track(session, str(tmp_path / "broken.mp3"))

    class BrokenBackend(FakeBackend):
        def analyze(self, path):
            raise AnalyzeError("bad file")

    result = analyze_tracks(session, BrokenBackend(), single_threaded=True)
    assert result.failed == 1 and result.analyzed == 0
    track = session.scalar(select(Track))
    assert track.last_analysis_error == "bad file"
    assert session.scalar(select(Features)) is None


def test_analyze_tracks_records_timeout(tmp_path, session):
    _add_track(session, str(tmp_path / "slow.mp3"))

    class SlowBackend(FakeBackend):
        def analyze(self, path):
            raise AnalyzeTimeout("exceeded 300s")

    result = analyze_tracks(session, SlowBackend(), single_threaded=True)
    assert result.failed == 1
    track = session.scalar(select(Track))
    assert "timeout" in track.last_analysis_error.lower()


def test_analyze_tracks_rescan_overwrites_existing(tmp_path, session):
    track = _add_track(session, str(tmp_path / "a.mp3"))
    analyze_tracks(session, FakeBackend(), single_threaded=True)
    original = session.get(Features, track.id).analyzed_at

    import time
    time.sleep(0.01)
    analyze_tracks(session, FakeBackend(), single_threaded=True, rescan=True)
    updated = session.get(Features, track.id).analyzed_at
    assert updated > original
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_analyzer.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `analyzer.py` (single-process path)**

Create `src/audio_tools/core/analyzer.py`:

```python
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Protocol, TypedDict

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.core.models import Features, Track


class FeatureDict(TypedDict, total=False):
    bpm: Optional[float]
    key: Optional[str]
    scale: Optional[str]
    energy: Optional[float]
    danceability: Optional[float]
    mood_happy: Optional[float]
    mood_sad: Optional[float]
    mood_aggressive: Optional[float]
    mood_relaxed: Optional[float]
    loudness: Optional[float]
    spectral_centroid: Optional[float]
    embedding: bytes  # 200-dim float32


class AnalyzeError(Exception):
    """Backend rejected the file (corrupt, unsupported, etc.)."""


class AnalyzeTimeout(Exception):
    """Backend exceeded its per-file timeout."""


class AnalyzerBackend(Protocol):
    def analyze(self, path: Path) -> FeatureDict: ...


@dataclass
class AnalyzeResult:
    analyzed: int = 0
    failed: int = 0


class FakeBackend:
    """Deterministic synthetic features. Used by tests and `--backend=fake`.

    Produces an embedding derived from the file path's SHA-1, so identical paths
    map to identical vectors. Numeric scalars are also path-stable.
    """

    def analyze(self, path: Path) -> FeatureDict:
        seed = int.from_bytes(hashlib.sha1(str(path).encode()).digest()[:8], "big") % (2**32)
        rng = np.random.default_rng(seed)
        emb = rng.standard_normal(200).astype(np.float32)
        return {
            "bpm": 60.0 + (seed % 140),
            "key": "C",
            "scale": "major",
            "energy": float((seed % 100) / 100.0),
            "danceability": float(((seed >> 8) % 100) / 100.0),
            "mood_happy": 0.5,
            "mood_sad": 0.5,
            "mood_aggressive": 0.5,
            "mood_relaxed": 0.5,
            "loudness": -12.0,
            "spectral_centroid": 2000.0,
            "embedding": emb.tobytes(),
        }


def _select_tracks_to_analyze(session: Session, rescan: bool) -> list[Track]:
    """Return tracks with no features OR features older than the track's mtime
    (which the scanner refreshes on file change), OR all tracks when rescan=True.
    """
    if rescan:
        return list(session.scalars(select(Track)).all())
    # outer-join: no features → analyze; or features.analyzed_at < epoch(track.mtime)
    stmt = select(Track).outerjoin(Features, Features.track_id == Track.id)
    rows: list[Track] = []
    for track in session.scalars(stmt).unique().all():
        f = session.get(Features, track.id)
        if f is None:
            rows.append(track)
            continue
        if f.analyzed_at.timestamp() < track.mtime:
            rows.append(track)
    return rows


def _upsert_features(session: Session, track_id: int, meta: FeatureDict) -> None:
    existing = session.get(Features, track_id)
    payload = {
        "track_id": track_id,
        "analyzed_at": datetime.utcnow(),
        **{k: meta.get(k) for k in (
            "bpm", "key", "scale", "energy", "danceability",
            "mood_happy", "mood_sad", "mood_aggressive", "mood_relaxed",
            "loudness", "spectral_centroid",
        )},
        "embedding": meta["embedding"],
    }
    if existing is None:
        session.add(Features(**payload))
    else:
        for k, v in payload.items():
            setattr(existing, k, v)


def analyze_tracks(
    session: Session,
    backend: AnalyzerBackend,
    *,
    single_threaded: bool = False,
    workers: Optional[int] = None,
    timeout_s: int = 300,
    rescan: bool = False,
) -> AnalyzeResult:
    """Analyze tracks that need (re-)analysis using *backend*.

    Single-threaded path is used by tests and the FakeBackend; the parallel
    path (Task 6) wraps the same backend in a ProcessPoolExecutor.
    """
    result = AnalyzeResult()
    tracks = _select_tracks_to_analyze(session, rescan=rescan)

    if single_threaded or len(tracks) <= 1:
        for track in tracks:
            try:
                meta = backend.analyze(Path(track.path))
            except AnalyzeTimeout as e:
                track.last_analysis_error = f"timeout: {e}"
                result.failed += 1
                continue
            except AnalyzeError as e:
                track.last_analysis_error = str(e)
                result.failed += 1
                continue
            track.last_analysis_error = None
            _upsert_features(session, track.id, meta)
            result.analyzed += 1
        session.commit()
        return result

    # Parallel path: implemented in Task 6.
    raise NotImplementedError("parallel path arrives in Task 6")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_analyzer.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/analyzer.py tests/unit/test_analyzer.py
git commit -m "feat(analyzer): backend protocol, FakeBackend, single-process driver"
```

---

## Task 6: Analyzer parallel path (`ProcessPoolExecutor`)

**Files:**
- Modify: `src/audio_tools/core/analyzer.py`
- Modify: `tests/unit/test_analyzer.py`

- [ ] **Step 1: Append a test** to `tests/unit/test_analyzer.py`:

```python
def test_analyze_tracks_parallel_uses_processpool(tmp_path, session, monkeypatch):
    """The parallel path must produce the same results as the single-threaded one."""
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        _add_track(session, str(tmp_path / name))

    result = analyze_tracks(session, FakeBackend(), single_threaded=False, workers=2)
    assert result.analyzed == 3
    rows = session.scalars(select(Features)).all()
    assert len(rows) == 3
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_analyzer.py::test_analyze_tracks_parallel_uses_processpool -v
```
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement parallel path**

Replace the trailing `raise NotImplementedError(...)` in `analyze_tracks` with:

```python
    # Parallel path
    import concurrent.futures as cf
    import os

    worker_count = workers or os.cpu_count() or 1
    # Snapshot to avoid holding live ORM objects in the subprocess
    work = [(t.id, t.path) for t in tracks]

    # Backend must be picklable. Both FakeBackend and EssentiaBackend are.
    backend_pickle = backend

    with cf.ProcessPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(_analyze_one, backend_pickle, path): track_id
            for track_id, path in work
        }
        for fut in cf.as_completed(futures):
            track_id = futures[fut]
            track = session.get(Track, track_id)
            try:
                meta = fut.result(timeout=timeout_s)
            except cf.TimeoutError:
                track.last_analysis_error = f"timeout: exceeded {timeout_s}s"
                result.failed += 1
                continue
            except AnalyzeTimeout as e:
                track.last_analysis_error = f"timeout: {e}"
                result.failed += 1
                continue
            except AnalyzeError as e:
                track.last_analysis_error = str(e)
                result.failed += 1
                continue
            track.last_analysis_error = None
            _upsert_features(session, track_id, meta)
            result.analyzed += 1

    session.commit()
    return result
```

And add the worker helper at module level (it must be importable in a subprocess):

```python
def _analyze_one(backend: AnalyzerBackend, path_str: str) -> FeatureDict:
    """Module-level subprocess entry point. Picklable backend required."""
    return backend.analyze(Path(path_str))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_analyzer.py -v
```
Expected: all 8 tests pass (the parallel test now passes).

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/analyzer.py tests/unit/test_analyzer.py
git commit -m "feat(analyzer): add ProcessPoolExecutor parallel path with per-task timeout"
```

---

## Task 7: `EssentiaBackend` + `fetch-models` CLI + golden test

The real backend imports Essentia lazily (so unit tests don't need it) and validates model presence at construction.

**Files:**
- Modify: `src/audio_tools/core/analyzer.py`
- Create: `src/audio_tools/core/model_registry.py`
- Create: `tests/golden/__init__.py`
- Create: `tests/golden/test_essentia_backend.py`

- [ ] **Step 1: Write the golden test**

Create `tests/golden/__init__.py` (empty) and `tests/golden/test_essentia_backend.py`:

```python
import importlib.util
from pathlib import Path

import pytest

from audio_tools.core.model_registry import EXPECTED_MODELS

essentia_available = importlib.util.find_spec("essentia") is not None
pytestmark = pytest.mark.skipif(not essentia_available, reason="essentia not installed")

FIXTURE = Path(__file__).parent.parent / "fixtures" / "audio" / "test_tagged.mp3"


def _models_present(models_dir: Path) -> bool:
    return all((models_dir / m.filename).exists() for m in EXPECTED_MODELS)


@pytest.fixture(scope="session")
def models_dir():
    from audio_tools import paths
    md = paths.models_dir()
    if not _models_present(md):
        pytest.skip(f"essentia models not present in {md}; run `audio-tools fetch-models`")
    return md


def test_essentia_backend_extracts_plausible_features(models_dir):
    from audio_tools.core.analyzer import EssentiaBackend

    backend = EssentiaBackend(models_dir=models_dir)
    meta = backend.analyze(FIXTURE)

    # The fixture is a 440Hz sine for 2s — these bounds are very loose by design.
    # We only assert that the backend RETURNS plausible values and the right shape.
    assert isinstance(meta["embedding"], bytes)
    assert len(meta["embedding"]) == 200 * 4
    assert meta["key"] in {
        "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
        "Db", "Eb", "Gb", "Ab", "Bb",
    }
    assert meta["scale"] in {"major", "minor"}
    if meta["bpm"] is not None:
        assert 0 < meta["bpm"] < 300
```

- [ ] **Step 2: Create the model registry**

Create `src/audio_tools/core/model_registry.py`:

```python
"""Pinned Essentia TF model files + their canonical URLs and SHA-256s.

URLs come from https://essentia.upf.edu/models/ — pinned at the time of writing.
Update by running `python -m audio_tools.core.model_registry --refresh-hashes`
(documented but not implemented here; first-class refresh is out of scope for Phase 2).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFile:
    filename: str
    url: str
    sha256: str  # hex digest


EXPECTED_MODELS: tuple[ModelFile, ...] = (
    ModelFile(
        filename="msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/feature-extractors/musicnn/msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_happy-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_happy/mood_happy-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_sad-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_sad/mood_sad-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_aggressive-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_aggressive/mood_aggressive-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_relaxed-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_relaxed/mood_relaxed-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
)
```

**Note on SHA-256s:** these are intentionally placeholders. The `fetch-models` command (Task 8) computes the actual hash after the first successful download and prints it for the developer to paste into this file. Subsequent fetches verify against the recorded hash. The pattern keeps the file source-controlled without committing 5 hashes that may rotate upstream.

- [ ] **Step 3: Add `EssentiaBackend` to `analyzer.py`**

Append at the bottom of `src/audio_tools/core/analyzer.py`:

```python
class EssentiaBackend:
    """Real Essentia + TF backend. Imports essentia lazily so the rest of the
    package stays import-safe when essentia isn't installed.

    Picklable: only holds the models_dir path. Each subprocess re-imports
    essentia and re-loads the TF models on first use.
    """

    def __init__(self, models_dir: Path):
        self._models_dir = Path(models_dir)
        from audio_tools.core.model_registry import EXPECTED_MODELS

        missing = [
            m.filename for m in EXPECTED_MODELS
            if not (self._models_dir / m.filename).exists()
        ]
        if missing:
            raise AnalyzeError(
                f"Missing essentia model files in {self._models_dir}: {missing}. "
                "Run `audio-tools fetch-models` first."
            )
        # Lazy-imported per worker:
        self._extractor = None
        self._musicnn = None
        self._moods: dict[str, object] = {}

    def _ensure_loaded(self) -> None:
        if self._extractor is not None:
            return
        import essentia.standard as es
        self._extractor = es.MusicExtractor(
            lowlevelStats=["mean"], rhythmStats=["mean"], tonalStats=["mean"]
        )
        self._musicnn = es.TensorflowPredictMusiCNN(
            graphFilename=str(self._models_dir / "msd-musicnn-1.pb"),
            output="model/dense/BiasAdd",
        )
        for mood in ("happy", "sad", "aggressive", "relaxed"):
            self._moods[mood] = es.TensorflowPredict2D(
                graphFilename=str(self._models_dir / f"mood_{mood}-msd-musicnn-1.pb"),
            )

    def analyze(self, path: Path) -> FeatureDict:
        self._ensure_loaded()
        import numpy as np
        try:
            features, _ = self._extractor(str(path))  # type: ignore[misc]
            bpm = float(features["rhythm.bpm"]) if "rhythm.bpm" in features.descriptorNames() else None
            key = features["tonal.key_edma.key"] if "tonal.key_edma.key" in features.descriptorNames() else None
            scale = features["tonal.key_edma.scale"] if "tonal.key_edma.scale" in features.descriptorNames() else None
            loudness = float(features["lowlevel.loudness_ebu128.integrated"]) if "lowlevel.loudness_ebu128.integrated" in features.descriptorNames() else None
            sc = float(features["lowlevel.spectral_centroid.mean"]) if "lowlevel.spectral_centroid.mean" in features.descriptorNames() else None
            danceability = float(features["rhythm.danceability"]) if "rhythm.danceability" in features.descriptorNames() else None
            energy = float(features["lowlevel.spectral_energy.mean"]) if "lowlevel.spectral_energy.mean" in features.descriptorNames() else None

            import essentia.standard as es
            audio = es.MonoLoader(filename=str(path), sampleRate=16000)()
            embedding_matrix = self._musicnn(audio)  # type: ignore[misc]
            embedding = np.asarray(embedding_matrix, dtype=np.float32).mean(axis=0)
            if embedding.shape[0] != 200:
                embedding = np.resize(embedding, 200).astype(np.float32)

            moods: dict[str, float] = {}
            for name, model in self._moods.items():
                pred = np.asarray(model(embedding_matrix), dtype=np.float32).mean(axis=0)
                moods[name] = float(pred[0])  # first class = positive label per Essentia models

            return {
                "bpm": bpm,
                "key": key,
                "scale": scale,
                "energy": energy,
                "danceability": danceability,
                "mood_happy": moods.get("happy"),
                "mood_sad": moods.get("sad"),
                "mood_aggressive": moods.get("aggressive"),
                "mood_relaxed": moods.get("relaxed"),
                "loudness": loudness,
                "spectral_centroid": sc,
                "embedding": embedding.astype(np.float32).tobytes(),
            }
        except Exception as e:  # pragma: no cover -- exercised only against real files
            raise AnalyzeError(f"Essentia failed on {path}: {e}") from e
```

- [ ] **Step 4: Run the golden test (will skip without essentia)**

```bash
python -m pytest tests/golden/ -v
```
Expected: SKIPPED (essentia not installed in CI/clean dev) or PASSED (if user has run `pip install -e ".[analysis]"` and `audio-tools fetch-models`).

- [ ] **Step 5: Run the full suite to confirm no regression**

```bash
python -m pytest -v
```
Expected: previous tests still pass; golden test SKIPPED.

- [ ] **Step 6: Commit**

```bash
git add src/audio_tools/core/analyzer.py src/audio_tools/core/model_registry.py tests/golden/__init__.py tests/golden/test_essentia_backend.py
git commit -m "feat(analyzer): add EssentiaBackend with model_registry and golden test"
```

---

## Task 8: `fetch-models` CLI subcommand

**Files:**
- Modify: `src/audio_tools/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_cli.py`:

```python
def test_cli_fetch_models_writes_files(tmp_path, monkeypatch):
    """Stub the downloader and assert files land in models_dir()."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    import audio_tools.cli as cli_mod
    calls = []

    def fake_download(url: str, dest: Path) -> str:
        calls.append((url, dest))
        dest.write_bytes(b"FAKE_MODEL")
        import hashlib
        return hashlib.sha256(b"FAKE_MODEL").hexdigest()

    monkeypatch.setattr(cli_mod, "_download_to_file", fake_download)

    runner = CliRunner()
    result = runner.invoke(main, ["fetch-models"])
    assert result.exit_code == 0, result.output

    from audio_tools.core.model_registry import EXPECTED_MODELS
    from audio_tools.paths import models_dir
    for m in EXPECTED_MODELS:
        assert (models_dir() / m.filename).exists()
    assert len(calls) == len(EXPECTED_MODELS)


def test_cli_fetch_models_skips_existing(tmp_path, monkeypatch):
    """If a file already exists with no hash to verify, fetch-models leaves it."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    from audio_tools.paths import models_dir
    from audio_tools.core.model_registry import EXPECTED_MODELS
    md = models_dir()
    md.mkdir(parents=True, exist_ok=True)
    for m in EXPECTED_MODELS:
        (md / m.filename).write_bytes(b"already here")

    import audio_tools.cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_download_to_file",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not download")),
    )

    runner = CliRunner()
    result = runner.invoke(main, ["fetch-models"])
    assert result.exit_code == 0
    assert "already present" in result.output.lower() or "skip" in result.output.lower()
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_cli.py::test_cli_fetch_models_writes_files -v
```
Expected: FAIL (`No such command 'fetch-models'`).

- [ ] **Step 3: Implement the subcommand**

Append to `src/audio_tools/cli.py` (after the existing `scan` definition):

```python
import hashlib

from audio_tools import paths as paths_mod
from audio_tools.core.model_registry import EXPECTED_MODELS, ModelFile


def _download_to_file(url: str, dest: Path) -> str:
    """Stream URL → dest atomically; return hex sha256 of the downloaded bytes.

    Tests monkeypatch this function — keep the signature stable.
    """
    import requests

    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    h.update(chunk)
    tmp.replace(dest)
    return h.hexdigest()


@main.command("fetch-models")
def fetch_models():
    """Download Essentia TF models into the user cache (~/.cache/audio-tools/models)."""
    target_dir = paths_mod.models_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    for m in EXPECTED_MODELS:
        dest = target_dir / m.filename
        if dest.exists():
            click.echo(f"  {m.filename}: already present, skipping")
            continue
        click.echo(f"  {m.filename}: downloading…")
        actual = _download_to_file(m.url, dest)
        if m.sha256 != "REPLACE_AT_FETCH_TIME" and actual != m.sha256:
            dest.unlink()
            raise click.ClickException(
                f"sha256 mismatch for {m.filename}: expected {m.sha256}, got {actual}"
            )
        if m.sha256 == "REPLACE_AT_FETCH_TIME":
            click.echo(f"    (record this hash in model_registry.py: {actual})")
    click.echo(f"Models ready in {target_dir}")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: all CLI tests pass (previous + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add fetch-models subcommand for Essentia TF models"
```

---

## Task 9: `analyze` CLI subcommand

**Files:**
- Modify: `src/audio_tools/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_cli.py`:

```python
def test_cli_analyze_with_fake_backend(tmp_path, monkeypatch):
    """`audio-tools analyze --backend=fake` should populate features."""
    _ensure_fixtures()
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    shutil.copy(FIXTURE_MP3, music / "b.mp3")

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")

    from audio_tools.core.db import Base, make_engine
    engine = make_engine(db)
    Base.metadata.create_all(engine)

    runner = CliRunner()
    # Scan first to populate tracks.
    assert runner.invoke(main, ["scan", str(music)]).exit_code == 0
    result = runner.invoke(main, ["analyze", "--backend=fake"])
    assert result.exit_code == 0, result.output
    assert "analyzed=2" in result.output


def test_cli_analyze_refuses_fake_without_env_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", raising=False)
    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "--backend=fake"])
    assert result.exit_code != 0
    assert "ALLOW_FAKE" in result.output or "fake backend" in result.output.lower()
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: new tests FAIL (`No such command 'analyze'`).

- [ ] **Step 3: Implement `analyze`**

Append to `src/audio_tools/cli.py`:

```python
from audio_tools.core import analyzer as analyzer_mod


def _build_backend(name: str) -> analyzer_mod.AnalyzerBackend:
    if name == "fake":
        if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND") != "1":
            raise click.UsageError(
                "fake backend disabled by default. Set AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1 to enable."
            )
        return analyzer_mod.FakeBackend()
    if name == "essentia":
        return analyzer_mod.EssentiaBackend(models_dir=paths_mod.models_dir())
    raise click.UsageError(f"Unknown backend: {name!r} (expected fake|essentia)")


@main.command()
@click.option("--backend", type=click.Choice(["fake", "essentia"]), default="essentia",
              show_default=True)
@click.option("--rescan", is_flag=True, help="Re-analyze every track, ignoring existing features.")
@click.option("--workers", type=int, default=None, help="Worker count (default: os.cpu_count()).")
@click.option("--timeout", type=int, default=300, show_default=True, help="Per-track timeout seconds.")
@click.option("--single-threaded", is_flag=True, help="Run in this process (mostly for debugging).")
def analyze(backend: str, rescan: bool, workers: Optional[int], timeout: int, single_threaded: bool):
    """Extract features for tracks that need analysis."""
    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    backend_impl = _build_backend(backend)
    with Session(engine, future=True) as session:
        result = analyzer_mod.analyze_tracks(
            session,
            backend_impl,
            single_threaded=single_threaded,
            workers=workers,
            timeout_s=timeout,
            rescan=rescan,
        )
    click.echo(f"Analyze complete: analyzed={result.analyzed} failed={result.failed}")
```

You'll also need to add `from typing import Optional` at the top of `cli.py` if not already present.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add analyze subcommand with fake/essentia backend selection"
```

---

## Task 10: `Clusterer.recluster` (full re-fit)

**Files:**
- Create: `src/audio_tools/core/clusterer.py`
- Create: `tests/unit/test_clusterer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_clusterer.py`:

```python
from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import select

from audio_tools.core.clusterer import ClusterError, assign_new, recluster
from audio_tools.core.models import Cluster, ClusterAssignment, Features, Track


def _seed_tracks_with_blob_embeddings(session, n_per_cluster: int = 5, k: int = 3):
    """Create n_per_cluster * k tracks whose embeddings are clearly separated."""
    rng = np.random.default_rng(0)
    for cluster_i in range(k):
        center = np.zeros(200, dtype=np.float32)
        center[cluster_i * 10:(cluster_i + 1) * 10] = 10.0  # disjoint signal
        for j in range(n_per_cluster):
            t = Track(path=f"/m/c{cluster_i}-t{j}.mp3", mtime=0.0, size=1)
            session.add(t)
            session.flush()
            emb = center + rng.standard_normal(200).astype(np.float32) * 0.1
            session.add(Features(
                track_id=t.id,
                embedding=emb.tobytes(),
                analyzed_at=datetime.utcnow(),
            ))
    session.commit()


def test_recluster_creates_k_clusters_and_assigns_all(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    n = recluster(session, k=3)
    assert n == 15
    clusters = session.scalars(select(Cluster)).all()
    assert len(clusters) == 3
    for c in clusters:
        assert c.k_value == 3
        assert len(c.centroid) == 200 * 4
        assert c.name.startswith("Cluster")
    assignments = session.scalars(select(ClusterAssignment)).all()
    assert len(assignments) == 15
    # Every track is in exactly one cluster
    track_ids = {a.track_id for a in assignments}
    assert len(track_ids) == 15


def test_recluster_groups_well_separated_points(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    # Group track ids by cluster, then verify track paths share their seeded cluster.
    by_cluster: dict[int, list[str]] = {}
    for assignment in session.scalars(select(ClusterAssignment)).all():
        track = session.get(Track, assignment.track_id)
        by_cluster.setdefault(assignment.cluster_id, []).append(track.path)
    for paths in by_cluster.values():
        prefixes = {p.split("/")[-1].split("-")[0] for p in paths}
        assert len(prefixes) == 1, f"cluster mixed seed groups: {prefixes}"


def test_recluster_overwrites_prior_clusters(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    recluster(session, k=2)
    assert len(session.scalars(select(Cluster)).all()) == 2
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_clusterer.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `clusterer.py` (recluster only)**

Create `src/audio_tools/core/clusterer.py`:

```python
from datetime import datetime
from typing import Sequence

import numpy as np
from sklearn.cluster import KMeans
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from audio_tools.core.models import Cluster, ClusterAssignment, Features


class ClusterError(Exception):
    """Raised when clustering preconditions are not met."""


def _load_embeddings(session: Session) -> tuple[list[int], np.ndarray]:
    rows = session.scalars(select(Features)).all()
    if not rows:
        raise ClusterError("no features rows; run `audio-tools analyze` first")
    track_ids = [r.track_id for r in rows]
    mat = np.stack([
        np.frombuffer(r.embedding, dtype=np.float32) for r in rows
    ])
    return track_ids, mat


def recluster(session: Session, k: int) -> int:
    """Run full KMeans on every feature row; rebuild clusters and assignments.

    Returns the number of tracks assigned.
    """
    if k < 2:
        raise ClusterError(f"k must be >= 2, got {k}")
    track_ids, embeddings = _load_embeddings(session)
    if embeddings.shape[0] < k:
        raise ClusterError(
            f"only {embeddings.shape[0]} feature rows, cannot cluster into k={k}"
        )

    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(embeddings)
    centroids = model.cluster_centers_.astype(np.float32)

    # Wipe and rebuild
    session.execute(delete(ClusterAssignment))
    session.execute(delete(Cluster))
    session.flush()

    now = datetime.utcnow()
    cluster_rows = [
        Cluster(
            name=f"Cluster {i + 1}",
            color=None,
            k_value=k,
            centroid=centroids[i].tobytes(),
            created_at=now,
        )
        for i in range(k)
    ]
    session.add_all(cluster_rows)
    session.flush()  # populate ids

    for tid, label, emb in zip(track_ids, labels, embeddings):
        c = cluster_rows[int(label)]
        distance = float(np.linalg.norm(emb - centroids[label]))
        session.add(ClusterAssignment(
            track_id=tid,
            cluster_id=c.id,
            distance=distance,
            assigned_at=now,
        ))
    session.commit()
    return len(track_ids)


def assign_new(session: Session) -> int:
    """Stub — implemented in Task 11."""
    raise NotImplementedError("assign_new arrives in Task 11")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_clusterer.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/clusterer.py tests/unit/test_clusterer.py
git commit -m "feat(clusterer): full KMeans re-fit + assignment writeback"
```

---

## Task 11: `Clusterer.assign_new` (incremental)

**Files:**
- Modify: `src/audio_tools/core/clusterer.py`
- Modify: `tests/unit/test_clusterer.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_clusterer.py`:

```python
def test_assign_new_routes_unassigned_to_nearest_cluster(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)

    # Add a new track whose embedding is dead-on cluster 0's center
    new = Track(path="/m/new.mp3", mtime=0.0, size=1)
    session.add(new); session.flush()
    seeded_center = np.zeros(200, dtype=np.float32)
    seeded_center[0:10] = 10.0
    session.add(Features(track_id=new.id, embedding=seeded_center.tobytes(), analyzed_at=datetime.utcnow()))
    session.commit()

    count = assign_new(session)
    assert count == 1

    a = session.get(ClusterAssignment, new.id)
    assert a is not None
    # The other 5 tracks seeded near center 0 share its cluster id.
    sibling_paths = [
        session.get(Track, x.track_id).path
        for x in session.scalars(select(ClusterAssignment).where(ClusterAssignment.cluster_id == a.cluster_id)).all()
        if x.track_id != new.id
    ]
    assert all("c0-" in p for p in sibling_paths)


def test_assign_new_is_idempotent(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    # No new tracks → 0 new assignments
    assert assign_new(session) == 0


def test_assign_new_without_clusters_raises(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    # Skip recluster; no clusters exist yet
    with pytest.raises(ClusterError, match="no clusters"):
        assign_new(session)


def test_assign_new_does_not_change_existing_assignments(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    before = {a.track_id: a.cluster_id for a in session.scalars(select(ClusterAssignment)).all()}

    # Add 3 new tracks belonging clearly to cluster 1
    seeded_center = np.zeros(200, dtype=np.float32)
    seeded_center[10:20] = 10.0
    for j in range(3):
        t = Track(path=f"/m/late-{j}.mp3", mtime=0.0, size=1)
        session.add(t); session.flush()
        session.add(Features(track_id=t.id, embedding=seeded_center.tobytes(), analyzed_at=datetime.utcnow()))
    session.commit()

    assign_new(session)

    after = {a.track_id: a.cluster_id for a in session.scalars(select(ClusterAssignment)).all()}
    for tid, cid in before.items():
        assert after[tid] == cid  # untouched
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_clusterer.py -v
```
Expected: 4 new tests FAIL (`NotImplementedError`).

- [ ] **Step 3: Implement `assign_new`**

Replace the stub `assign_new` in `src/audio_tools/core/clusterer.py` with:

```python
def assign_new(session: Session) -> int:
    """Assign tracks whose features exist but have no cluster_assignments row.

    Uses the nearest existing centroid; never modifies existing assignments.
    Returns the count of new assignments.
    """
    clusters = session.scalars(select(Cluster)).all()
    if not clusters:
        raise ClusterError("no clusters; run `audio-tools cluster --k N` first")

    centroids = np.stack([
        np.frombuffer(c.centroid, dtype=np.float32) for c in clusters
    ])
    cluster_ids = [c.id for c in clusters]

    unassigned_stmt = (
        select(Features)
        .outerjoin(ClusterAssignment, ClusterAssignment.track_id == Features.track_id)
        .where(ClusterAssignment.track_id.is_(None))
    )
    unassigned = session.scalars(unassigned_stmt).all()
    if not unassigned:
        return 0

    now = datetime.utcnow()
    for feat in unassigned:
        emb = np.frombuffer(feat.embedding, dtype=np.float32)
        distances = np.linalg.norm(centroids - emb, axis=1)
        best = int(np.argmin(distances))
        session.add(ClusterAssignment(
            track_id=feat.track_id,
            cluster_id=cluster_ids[best],
            distance=float(distances[best]),
            assigned_at=now,
        ))
    session.commit()
    return len(unassigned)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_clusterer.py -v
```
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/clusterer.py tests/unit/test_clusterer.py
git commit -m "feat(clusterer): add incremental assign_new for tracks without a cluster"
```

---

## Task 12: `cluster` CLI subcommand

**Files:**
- Modify: `src/audio_tools/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_cli.py`:

```python
def test_cli_cluster_initial_uses_default_k(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"; music.mkdir()
    # Need enough tracks: default k=6, plan B (smaller default for tests)
    # We'll pass an explicit --k=2 for stability.
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    shutil.copy(FIXTURE_MP3, music / "b.mp3")
    shutil.copy(FIXTURE_MP3, music / "c.mp3")

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    runner = CliRunner()
    assert runner.invoke(main, ["scan", str(music)]).exit_code == 0
    assert runner.invoke(main, ["analyze", "--backend=fake"]).exit_code == 0
    result = runner.invoke(main, ["cluster", "--k=2", "--force"])
    assert result.exit_code == 0, result.output
    assert "clusters=2" in result.output


def test_cli_cluster_incremental_when_clusters_exist(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"; music.mkdir()
    for n in ("a.mp3", "b.mp3", "c.mp3", "d.mp3"):
        shutil.copy(FIXTURE_MP3, music / n)

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    runner = CliRunner()
    runner.invoke(main, ["scan", str(music)])
    runner.invoke(main, ["analyze", "--backend=fake"])
    runner.invoke(main, ["cluster", "--k=2", "--force"])

    # Add a new track, re-scan, re-analyze, then cluster with no args → incremental
    shutil.copy(FIXTURE_MP3, music / "new.mp3")
    runner.invoke(main, ["scan", str(music)])
    runner.invoke(main, ["analyze", "--backend=fake"])
    result = runner.invoke(main, ["cluster"])
    assert result.exit_code == 0, result.output
    assert "assigned=1" in result.output
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: new tests FAIL (`No such command 'cluster'`).

- [ ] **Step 3: Implement `cluster`**

Append to `src/audio_tools/cli.py`:

```python
from audio_tools.core import clusterer as clusterer_mod
from audio_tools.core.models import Cluster as ClusterModel


@main.command()
@click.option("--k", type=int, default=None, help="Number of clusters (forces a full re-fit). Default 6 if no clusters exist.")
@click.option("--incremental", is_flag=True, help="Force incremental mode (refuse to re-fit).")
@click.option("--force", is_flag=True, help="Skip the confirmation prompt for destructive re-fit.")
def cluster(k: Optional[int], incremental: bool, force: bool):
    """Cluster tracks by feature embedding."""
    if k is not None and incremental:
        raise click.UsageError("--k and --incremental are mutually exclusive")

    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    with Session(engine, future=True) as session:
        existing = session.scalar(select(ClusterModel)) is not None

        if incremental or (k is None and existing):
            try:
                assigned = clusterer_mod.assign_new(session)
            except clusterer_mod.ClusterError as e:
                raise click.ClickException(str(e))
            click.echo(f"Cluster (incremental): assigned={assigned}")
            return

        target_k = k if k is not None else 6
        if existing and not force:
            click.confirm(
                f"This will discard existing clusters and re-fit with k={target_k}. Continue?",
                abort=True,
            )
        try:
            n = clusterer_mod.recluster(session, k=target_k)
        except clusterer_mod.ClusterError as e:
            raise click.ClickException(str(e))
        click.echo(f"Cluster complete: clusters={target_k} tracks={n}")
```

Add `from sqlalchemy import select` at the top if not already present.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: all CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add cluster subcommand (re-fit and incremental modes)"
```

---

## Task 13: `PlaylistBuilder` + tests

**Files:**
- Create: `src/audio_tools/core/playlist_builder.py`
- Create: `tests/unit/test_playlist_builder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_playlist_builder.py`:

```python
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from audio_tools.core.models import Cluster, ClusterAssignment, Features, Track
from audio_tools.core.playlist_builder import _sanitize_filename, write_playlists


def _make_cluster(session, name: str) -> Cluster:
    c = Cluster(
        name=name, color=None, k_value=2,
        centroid=np.zeros(200, dtype=np.float32).tobytes(),
        created_at=datetime.utcnow(),
    )
    session.add(c); session.flush()
    return c


def _assign(session, track: Track, cluster: Cluster, distance: float) -> None:
    session.add(ClusterAssignment(
        track_id=track.id, cluster_id=cluster.id, distance=distance,
        assigned_at=datetime.utcnow(),
    ))


def test_write_playlists_emits_extm3u_with_extinf(session, tmp_path):
    t1 = Track(path="/m/song1.mp3", mtime=0.0, size=1, title="Song One", artist="A", duration_s=180.0)
    t2 = Track(path="/m/song2.mp3", mtime=0.0, size=1, title="Song Two", artist="B", duration_s=240.0)
    session.add_all([t1, t2]); session.flush()
    c = _make_cluster(session, "Workout")
    _assign(session, t1, c, distance=0.1)
    _assign(session, t2, c, distance=0.5)
    session.commit()

    written = write_playlists(session, out_dir=tmp_path)
    assert len(written) == 1
    body = written[0].read_text(encoding="utf-8")
    assert body.startswith("#EXTM3U")
    # Nearest-to-centroid first (distance 0.1 before 0.5)
    assert body.index("song1.mp3") < body.index("song2.mp3")
    assert "#EXTINF:180,A - Song One" in body
    assert "#EXTINF:240,B - Song Two" in body


def test_write_playlists_skips_empty_clusters(session, tmp_path):
    _make_cluster(session, "Empty")
    session.commit()
    written = write_playlists(session, out_dir=tmp_path)
    assert written == []


def test_filename_sanitization():
    assert _sanitize_filename("Workout") == "Workout"
    assert _sanitize_filename("My Mix #1") == "My_Mix_1"
    assert _sanitize_filename("///") == ""
    assert _sanitize_filename("late-night/jazz") == "late-night_jazz"
    assert _sanitize_filename("") == ""


def test_write_playlists_falls_back_to_cluster_id_for_unsafe_name(session, tmp_path):
    t = Track(path="/m/x.mp3", mtime=0.0, size=1, duration_s=100.0)
    session.add(t); session.flush()
    c = _make_cluster(session, "///")  # sanitizes to empty
    _assign(session, t, c, distance=0.0)
    session.commit()

    written = write_playlists(session, out_dir=tmp_path)
    assert len(written) == 1
    assert written[0].name == f"cluster_{c.id}.m3u"
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_playlist_builder.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `playlist_builder.py`**

Create `src/audio_tools/core/playlist_builder.py`:

```python
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.core.models import Cluster, ClusterAssignment, Track

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    """Sanitize a cluster name into a safe filename stem (no extension).

    Replaces runs of disallowed characters with a single underscore and trims
    leading/trailing underscores. Returns empty string when sanitization wipes
    the whole input.
    """
    stripped = _SANITIZE_RE.sub("_", name).strip("_")
    return stripped


def _build_body(rows: list[tuple[Track, ClusterAssignment]]) -> str:
    """Render rows (sorted nearest-to-centroid first) as EXTM3U text."""
    out = ["#EXTM3U"]
    for track, _assignment in rows:
        duration = int(track.duration_s) if track.duration_s is not None else -1
        artist = track.artist or ""
        title = track.title or Path(track.path).stem
        out.append(f"#EXTINF:{duration},{artist} - {title}")
        out.append(track.path)
    out.append("")  # trailing newline
    return "\n".join(out)


def write_playlists(session: Session, out_dir: Path) -> list[Path]:
    """Write one m3u per non-empty cluster into out_dir; return written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for cluster in session.scalars(select(Cluster)).all():
        stmt = (
            select(Track, ClusterAssignment)
            .join(ClusterAssignment, ClusterAssignment.track_id == Track.id)
            .where(ClusterAssignment.cluster_id == cluster.id)
            .order_by(ClusterAssignment.distance.asc())
        )
        rows = session.execute(stmt).all()
        if not rows:
            continue
        stem = _sanitize_filename(cluster.name) or f"cluster_{cluster.id}"
        path = out_dir / f"{stem}.m3u"
        path.write_text(_build_body([(t, a) for (t, a) in rows]), encoding="utf-8")
        written.append(path)
    return written
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_playlist_builder.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/core/playlist_builder.py tests/unit/test_playlist_builder.py
git commit -m "feat(playlist_builder): write per-cluster EXTM3U files sorted by distance"
```

---

## Task 14: `playlists` CLI subcommand

**Files:**
- Modify: `src/audio_tools/cli.py`
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: Append tests** to `tests/unit/test_cli.py`:

```python
def test_cli_playlists_writes_one_file_per_cluster(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"; music.mkdir()
    for n in ("a.mp3", "b.mp3", "c.mp3", "d.mp3"):
        shutil.copy(FIXTURE_MP3, music / n)

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    runner = CliRunner()
    runner.invoke(main, ["scan", str(music)])
    runner.invoke(main, ["analyze", "--backend=fake"])
    runner.invoke(main, ["cluster", "--k=2", "--force"])

    out = tmp_path / "playlists"
    result = runner.invoke(main, ["playlists", f"--out-dir={out}"])
    assert result.exit_code == 0, result.output
    assert out.is_dir()
    written = list(out.glob("*.m3u"))
    assert 1 <= len(written) <= 2  # FakeBackend may produce singleton or split clusters
    for p in written:
        body = p.read_text(encoding="utf-8")
        assert body.startswith("#EXTM3U")
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/unit/test_cli.py::test_cli_playlists_writes_one_file_per_cluster -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `playlists`**

Append to `src/audio_tools/cli.py`:

```python
from audio_tools.core import playlist_builder as playlist_mod


@main.command()
@click.option("--out-dir", type=click.Path(file_okay=False, path_type=Path), default=None,
              help="Directory to write m3u files (default: XDG playlists dir).")
def playlists(out_dir: Optional[Path]):
    """Write one m3u per cluster to OUT_DIR."""
    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    target_dir = out_dir or paths_mod.playlists_dir()
    with Session(engine, future=True) as session:
        written = playlist_mod.write_playlists(session, target_dir)
    click.echo(f"Wrote {len(written)} playlist(s) to {target_dir}")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/unit/test_cli.py -v
```
Expected: all CLI tests pass.

- [ ] **Step 5: Manual smoke test (optional)**

```bash
audio-tools --help     # confirm scan/analyze/cluster/playlists/fetch-models all listed
```

- [ ] **Step 6: Commit**

```bash
git add src/audio_tools/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add playlists subcommand for per-cluster m3u export"
```

---

## Task 15: README update for Phase 2

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README contents**

Overwrite `README.md`:

```markdown
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
audio-tools cluster --k 6              # k-means clustering
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
```

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for Phase 2 (analyze/cluster/playlists/fetch-models)"
```

---

## Phase 2 Completion Checklist

After Task 15, verify:

- [ ] `pytest -v` reports 100% pass (golden test SKIPPED unless essentia installed)
- [ ] `audio-tools --help` lists `scan`, `fetch-models`, `analyze`, `cluster`, `playlists`
- [ ] With `AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1`: `audio-tools scan <dir> && audio-tools analyze --backend=fake && audio-tools cluster --k 2 --force && audio-tools playlists` writes m3u files
- [ ] `alembic upgrade head` from a fresh DB applies 0001 → 0004 cleanly
- [ ] With Essentia installed and models fetched: golden test passes

When all checked: Phase 2 is done. Phase 3 (TransferPlanner + Transcoder + transfer execution) and Phase 4 (GUI) are planned next.
