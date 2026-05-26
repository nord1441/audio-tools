from pathlib import Path

import pytest

from audio_tools.core import tags

FIXTURES = Path(__file__).parent.parent / "fixtures" / "audio"


@pytest.fixture(scope="session", autouse=True)
def ensure_fixtures():
    if not (FIXTURES / "test_tagged.mp3").exists():
        import subprocess
        script = FIXTURES.parent / "generate_audio_fixtures.sh"
        subprocess.run(["bash", str(script)], check=True)


def test_read_tags_extracts_title_artist_album():
    meta = tags.read_tags(FIXTURES / "test_tagged.mp3")
    assert meta["title"] == "Test Title"
    assert meta["artist"] == "Test Artist"
    assert meta["album"] == "Test Album"


def test_read_tags_returns_duration_in_seconds():
    meta = tags.read_tags(FIXTURES / "test_tagged.mp3")
    assert meta["duration_s"] == pytest.approx(2.0, abs=0.2)


def test_read_tags_returns_codec_and_bitrate():
    meta = tags.read_tags(FIXTURES / "test_tagged.mp3")
    assert meta["codec"] == "mp3"
    assert 100 <= meta["bitrate"] <= 200  # ~128


def test_read_tags_handles_untagged_file():
    meta = tags.read_tags(FIXTURES / "test_untagged.mp3")
    assert meta["title"] is None
    assert meta["artist"] is None
    assert meta["codec"] == "mp3"


def test_read_tags_raises_on_unsupported_file(tmp_path):
    bad = tmp_path / "not_audio.txt"
    bad.write_text("hello")
    with pytest.raises(tags.UnsupportedAudioError):
        tags.read_tags(bad)
