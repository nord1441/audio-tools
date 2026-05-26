"""Render a track relpath into an m3u line per the device profile's preference."""
from pathlib import PurePath

ALLOWED = frozenset({"relative", "windows_backslash", "absolute"})


def format_path(relpath: PurePath, style: str) -> str:
    if style == "relative":
        return str(relpath)
    if style == "windows_backslash":
        return str(relpath).replace("/", "\\")
    if style == "absolute":
        return "/" + str(relpath)
    raise ValueError(f"unknown m3u_path_style: {style!r}")
