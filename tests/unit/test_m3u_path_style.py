from pathlib import PurePath

import pytest

from audio_tools.core.m3u_path_style import format_path


def test_relative():
    assert format_path(PurePath("Music/foo.mp3"), "relative") == "Music/foo.mp3"


def test_windows_backslash():
    assert format_path(PurePath("Music/foo/bar.mp3"), "windows_backslash") == "Music\\foo\\bar.mp3"


def test_absolute_prefixes_slash():
    assert format_path(PurePath("Music/foo.mp3"), "absolute") == "/Music/foo.mp3"


def test_unknown_style_raises():
    with pytest.raises(ValueError, match="unknown m3u_path_style"):
        format_path(PurePath("foo.mp3"), "weird")
