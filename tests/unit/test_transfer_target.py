from pathlib import Path, PurePath

import pytest

from audio_tools.core.transfer_target import LocalDirectoryTarget


def test_local_target_requires_existing_directory(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        LocalDirectoryTarget(tmp_path / "missing")


def test_local_target_copy_and_exists(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    src = tmp_path / "src.mp3"
    src.write_bytes(b"hello")

    rel = PurePath("Music/foo/bar.mp3")
    assert not target.exists(rel)
    target.copy_file(src, rel)
    assert target.exists(rel)
    assert (root / "Music/foo/bar.mp3").read_bytes() == b"hello"


def test_local_target_file_sha1(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    src = tmp_path / "src.mp3"; src.write_bytes(b"hello")
    target.copy_file(src, PurePath("a.mp3"))

    import hashlib
    assert target.file_sha1(PurePath("a.mp3")) == hashlib.sha1(b"hello").hexdigest()
    assert target.file_sha1(PurePath("missing.mp3")) is None


def test_local_target_available_bytes(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    avail = target.available_bytes()
    assert isinstance(avail, int) and avail > 0


def test_local_target_remove_and_write_text(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    target.write_text(PurePath("playlists/p.m3u"), "#EXTM3U\n/abs/a.mp3\n")
    assert (root / "playlists/p.m3u").read_text() == "#EXTM3U\n/abs/a.mp3\n"
    target.remove(PurePath("playlists/p.m3u"))
    assert not target.exists(PurePath("playlists/p.m3u"))


def test_local_target_remove_missing_is_noop(tmp_path):
    root = tmp_path / "dev"; root.mkdir()
    target = LocalDirectoryTarget(root)
    target.remove(PurePath("nope.mp3"))  # must not raise
