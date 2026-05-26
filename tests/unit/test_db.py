from sqlalchemy import select

from audio_tools.core.models import Track


def test_track_can_be_inserted_and_queried(session):
    t = Track(
        path="/music/foo.mp3",
        mtime=1700000000.0,
        size=1024,
        sha1=None,
    )
    session.add(t)
    session.commit()

    rows = session.scalars(select(Track)).all()
    assert len(rows) == 1
    assert rows[0].path == "/music/foo.mp3"
    assert rows[0].id is not None


def test_track_path_is_unique(session):
    session.add(Track(path="/music/dup.mp3", mtime=0.0, size=1))
    session.commit()
    session.add(Track(path="/music/dup.mp3", mtime=0.0, size=2))
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.commit()


def test_track_optional_metadata_fields(session):
    t = Track(
        path="/music/bar.mp3",
        mtime=0.0,
        size=0,
        title="Bar",
        artist="Some Artist",
        album="Some Album",
        duration_s=180.5,
        codec="mp3",
        bitrate=192,
    )
    session.add(t)
    session.commit()
    fetched = session.scalars(select(Track)).first()
    assert fetched.title == "Bar"
    assert fetched.duration_s == 180.5


from audio_tools.core.models import DeviceProfile


def test_device_profile_can_be_inserted(session):
    p = DeviceProfile(
        name="walkman",
        mount_hint="/run/media/$USER/WALKMAN",
        codec="opus",
        container="ogg",
        max_bitrate=128,
        min_bitrate=64,
        bitrate_step=32,
        max_size_bytes=14_000_000_000,
        sample_rate_max=48000,
        m3u_path_style="relative",
        folder_layout="{artist}/{album}/{track:02d} - {title}",
    )
    session.add(p)
    session.commit()

    fetched = session.get(DeviceProfile, p.id)
    assert fetched.name == "walkman"
    assert fetched.codec == "opus"
    assert fetched.max_size_bytes == 14_000_000_000


def test_device_profile_name_unique(session):
    session.add(DeviceProfile(
        name="dup", codec="mp3", container="mp3",
        max_bitrate=192, min_bitrate=64, bitrate_step=32,
        max_size_bytes=1_000_000_000, sample_rate_max=44100,
        m3u_path_style="relative", folder_layout="{title}",
    ))
    session.commit()
    session.add(DeviceProfile(
        name="dup", codec="mp3", container="mp3",
        max_bitrate=192, min_bitrate=64, bitrate_step=32,
        max_size_bytes=1_000_000_000, sample_rate_max=44100,
        m3u_path_style="relative", folder_layout="{title}",
    ))
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        session.commit()


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


def test_transfer_session_insert_and_query(session):
    profile = DeviceProfile(
        name="walkman", codec="opus", container="ogg",
        max_bitrate=128, min_bitrate=64, bitrate_step=32,
        max_size_bytes=14_000_000_000, sample_rate_max=48000,
        m3u_path_style="relative", folder_layout="{artist}/{title}",
    )
    session.add(profile); session.flush()

    from audio_tools.core.models import TransferSession
    ts = TransferSession(
        profile_id=profile.id,
        started_at=datetime(2026, 5, 26, 13, 0, 0),
        status="running",
        bytes_transferred=0,
        bitrate_kbps=128,
        kept_count=42,
        dropped_count=3,
    )
    session.add(ts); session.commit()

    fetched = session.get(TransferSession, ts.id)
    assert fetched.status == "running"
    assert fetched.bitrate_kbps == 128
    assert fetched.kept_count == 42
    assert fetched.profile_id == profile.id
