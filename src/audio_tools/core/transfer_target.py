"""Transfer destinations: USB mounts, gvfs MTP paths.

LocalDirectoryTarget covers both because gvfs exposes MTP devices as ordinary
filesystem paths under /run/user/$UID/gvfs/. Future MTPTarget can be added
behind this same Protocol.
"""
import shutil
from pathlib import Path, PurePath
from typing import Protocol

from audio_tools.core.hashing import sha1_of


class TransferTarget(Protocol):
    def exists(self, relpath: PurePath) -> bool: ...
    def file_sha1(self, relpath: PurePath) -> str | None: ...
    def available_bytes(self) -> int: ...
    def copy_file(self, src: Path, relpath: PurePath) -> None: ...
    def remove(self, relpath: PurePath) -> None: ...
    def write_text(self, relpath: PurePath, text: str) -> None: ...


class LocalDirectoryTarget:
    """Target backed by an existing directory (USB mount, gvfs MTP, plain dir)."""

    def __init__(self, root: Path):
        root = Path(root)
        if not root.is_dir():
            raise ValueError(f"target root is not a directory: {root}")
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, relpath: PurePath) -> Path:
        return self._root / relpath

    def exists(self, relpath: PurePath) -> bool:
        return self._resolve(relpath).is_file()

    def file_sha1(self, relpath: PurePath) -> str | None:
        p = self._resolve(relpath)
        return sha1_of(p) if p.is_file() else None

    def available_bytes(self) -> int:
        return shutil.disk_usage(self._root).free

    def copy_file(self, src: Path, relpath: PurePath) -> None:
        dst = self._resolve(relpath)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def remove(self, relpath: PurePath) -> None:
        p = self._resolve(relpath)
        if p.is_file():
            p.unlink()

    def write_text(self, relpath: PurePath, text: str) -> None:
        dst = self._resolve(relpath)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
