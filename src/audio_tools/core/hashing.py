"""Filesystem hashing helpers shared by scanner and transfer modules."""
import hashlib
from pathlib import Path

_HASH_CHUNK = 1024 * 1024  # 1 MiB


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
