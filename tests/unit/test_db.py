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
