from pathlib import Path

import pytest
from sqlalchemy import select

from audio_tools.core import device_profile as dp
from audio_tools.core.models import DeviceProfile


VALID_YAML = """
name: walkman
mount_hint: /run/media/$USER/WALKMAN
codec: opus
container: ogg
max_bitrate: 128
min_bitrate: 64
bitrate_step: 32
max_size_bytes: 14000000000
sample_rate_max: 48000
m3u_path_style: relative
folder_layout: "{artist}/{album}/{track:02d} - {title}"
"""


def test_load_profile_from_string():
    profile = dp.parse_profile(VALID_YAML)
    assert profile["name"] == "walkman"
    assert profile["codec"] == "opus"
    assert profile["max_bitrate"] == 128
    assert profile["max_size_bytes"] == 14_000_000_000


def test_load_profile_from_file(tmp_path):
    f = tmp_path / "walkman.yaml"
    f.write_text(VALID_YAML)
    profile = dp.load_profile_file(f)
    assert profile["name"] == "walkman"


def test_invalid_codec_rejected():
    bad = VALID_YAML.replace("codec: opus", "codec: midi")
    with pytest.raises(dp.InvalidProfileError, match="codec"):
        dp.parse_profile(bad)


def test_missing_required_field_rejected():
    bad = "\n".join(line for line in VALID_YAML.splitlines() if not line.startswith("max_bitrate"))
    with pytest.raises(dp.InvalidProfileError, match="max_bitrate"):
        dp.parse_profile(bad)


def test_min_bitrate_must_not_exceed_max():
    bad = VALID_YAML.replace("min_bitrate: 64", "min_bitrate: 256")
    with pytest.raises(dp.InvalidProfileError, match="min_bitrate"):
        dp.parse_profile(bad)


def test_upsert_inserts_new_profile(session, tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text(VALID_YAML)
    dp.upsert_profile(f, session)
    rows = session.scalars(select(DeviceProfile)).all()
    assert len(rows) == 1
    assert rows[0].name == "walkman"
    assert rows[0].max_bitrate == 128


def test_upsert_updates_existing_profile(session, tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text(VALID_YAML)
    dp.upsert_profile(f, session)

    updated = VALID_YAML.replace("max_bitrate: 128", "max_bitrate: 96")
    f.write_text(updated)
    dp.upsert_profile(f, session)

    rows = session.scalars(select(DeviceProfile)).all()
    assert len(rows) == 1
    assert rows[0].max_bitrate == 96


def test_load_all_profiles_from_dir(session, tmp_path):
    (tmp_path / "a.yaml").write_text(VALID_YAML)
    (tmp_path / "b.yaml").write_text(VALID_YAML.replace("name: walkman", "name: phone"))
    (tmp_path / "ignored.txt").write_text("not yaml")

    count = dp.load_all_profiles(tmp_path, session)
    assert count == 2
    names = sorted(r.name for r in session.scalars(select(DeviceProfile)).all())
    assert names == ["phone", "walkman"]
