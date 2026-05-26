import hashlib
from pathlib import Path

from audio_tools.core.hashing import sha1_of


def test_sha1_of_matches_hashlib(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello world" * 1000)
    expected = hashlib.sha1(f.read_bytes()).hexdigest()
    assert sha1_of(f) == expected


def test_sha1_of_empty_file(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert sha1_of(f) == hashlib.sha1(b"").hexdigest()


def test_sha1_of_multi_chunk_file(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(b"A" * (1024 * 1024 * 3 + 17))
    expected = hashlib.sha1(b"A" * (1024 * 1024 * 3 + 17)).hexdigest()
    assert sha1_of(f) == expected
