from pathlib import Path

from audio_tools.core.scanner import discover_audio_files


def _touch(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_discover_finds_supported_extensions(tmp_path):
    _touch(tmp_path / "a.mp3")
    _touch(tmp_path / "sub" / "b.flac")
    _touch(tmp_path / "sub" / "c.ogg")
    _touch(tmp_path / "sub" / "d.opus")
    _touch(tmp_path / "sub" / "e.m4a")
    _touch(tmp_path / "ignore.txt")
    _touch(tmp_path / "image.jpg")

    found = sorted(p.name for p in discover_audio_files(tmp_path))
    assert found == ["a.mp3", "b.flac", "c.ogg", "d.opus", "e.m4a"]


def test_discover_is_case_insensitive(tmp_path):
    _touch(tmp_path / "Loud.MP3")
    _touch(tmp_path / "Quiet.Flac")
    assert len(list(discover_audio_files(tmp_path))) == 2


def test_discover_returns_absolute_paths(tmp_path):
    _touch(tmp_path / "a.mp3")
    for p in discover_audio_files(tmp_path):
        assert p.is_absolute()


def test_discover_empty_dir(tmp_path):
    assert list(discover_audio_files(tmp_path)) == []


from sqlalchemy import select

from audio_tools.core.scanner import scan, ScanResult
from audio_tools.core.models import Track


def _make_real_mp3(dst: Path) -> None:
    """Copy the tagged fixture so tags.read_tags succeeds."""
    import shutil
    src = Path(__file__).parent.parent / "fixtures" / "audio" / "test_tagged.mp3"
    if not src.exists():
        import subprocess
        subprocess.run(["bash", str(src.parent.parent / "generate_audio_fixtures.sh")], check=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def test_scan_inserts_new_tracks(tmp_path, session):
    _make_real_mp3(tmp_path / "a.mp3")
    _make_real_mp3(tmp_path / "sub" / "b.mp3")

    result = scan(tmp_path, session)

    assert isinstance(result, ScanResult)
    assert result.added == 2
    assert result.updated == 0
    assert result.removed == 0
    assert result.moved == 0

    rows = session.scalars(select(Track)).all()
    assert len(rows) == 2
    assert {r.title for r in rows} == {"Test Title"}


def test_scan_persists_basic_metadata(tmp_path, session):
    _make_real_mp3(tmp_path / "a.mp3")
    scan(tmp_path, session)

    track = session.scalars(select(Track)).first()
    assert track.path == str((tmp_path / "a.mp3").resolve())
    assert track.codec == "mp3"
    assert track.bitrate is not None
    assert track.duration_s is not None
    assert track.size > 0
    assert track.mtime > 0


def test_scan_skips_files_that_mutagen_rejects(tmp_path, session):
    # Plain text with .mp3 extension — mutagen will reject
    (tmp_path / "bogus.mp3").write_text("not actually audio")
    _make_real_mp3(tmp_path / "good.mp3")

    result = scan(tmp_path, session)
    assert result.added == 1
    assert result.skipped == 1
    rows = session.scalars(select(Track)).all()
    assert len(rows) == 1
    assert rows[0].path.endswith("good.mp3")
