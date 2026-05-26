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
