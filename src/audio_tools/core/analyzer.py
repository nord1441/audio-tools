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


def _analyze_one(backend: "AnalyzerBackend", path_str: str) -> "FeatureDict":
    """Module-level subprocess entry point. Picklable backend required."""
    return backend.analyze(Path(path_str))


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
