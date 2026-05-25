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
