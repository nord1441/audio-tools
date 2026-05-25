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
