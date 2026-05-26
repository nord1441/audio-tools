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
