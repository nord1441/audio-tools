from pathlib import Path
from typing import TypedDict

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.core.models import DeviceProfile

ALLOWED_CODECS = frozenset({"opus", "mp3", "aac", "copy"})
ALLOWED_CONTAINERS = frozenset({"ogg", "mp3", "m4a"})
ALLOWED_PATH_STYLES = frozenset({"relative", "windows_backslash", "absolute"})

REQUIRED_FIELDS = (
    "name", "codec", "container",
    "max_bitrate", "min_bitrate", "bitrate_step",
    "max_size_bytes", "sample_rate_max",
    "m3u_path_style", "folder_layout",
)


class ProfileDict(TypedDict, total=False):
    name: str
    mount_hint: str | None
    codec: str
    container: str
    max_bitrate: int
    min_bitrate: int
    bitrate_step: int
    max_size_bytes: int
    sample_rate_max: int
    m3u_path_style: str
    folder_layout: str


class InvalidProfileError(ValueError):
    pass


def parse_profile(text: str) -> ProfileDict:
    """Parse and validate YAML. Returns a plain dict; does not touch DB."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise InvalidProfileError(f"YAML parse error: {e}") from e
    if not isinstance(data, dict):
        raise InvalidProfileError("Profile must be a YAML mapping")

    for field in REQUIRED_FIELDS:
        if field not in data:
            raise InvalidProfileError(f"Missing required field: {field}")

    if data["codec"] not in ALLOWED_CODECS:
        raise InvalidProfileError(
            f"Invalid codec {data['codec']!r}; allowed: {sorted(ALLOWED_CODECS)}"
        )
    if data["container"] not in ALLOWED_CONTAINERS:
        raise InvalidProfileError(
            f"Invalid container {data['container']!r}; allowed: {sorted(ALLOWED_CONTAINERS)}"
        )
    if data["m3u_path_style"] not in ALLOWED_PATH_STYLES:
        raise InvalidProfileError(
            f"Invalid m3u_path_style {data['m3u_path_style']!r}"
        )
    if data["min_bitrate"] > data["max_bitrate"]:
        raise InvalidProfileError(
            f"min_bitrate ({data['min_bitrate']}) must not exceed "
            f"max_bitrate ({data['max_bitrate']})"
        )

    data.setdefault("mount_hint", None)
    return data  # type: ignore[return-value]


def load_profile_file(path: Path) -> ProfileDict:
    return parse_profile(path.read_text(encoding="utf-8"))


def upsert_profile(path: Path, session: Session) -> DeviceProfile:
    data = load_profile_file(path)
    existing = session.scalar(
        select(DeviceProfile).where(DeviceProfile.name == data["name"])
    )
    if existing is None:
        record = DeviceProfile(**data)
        session.add(record)
    else:
        for k, v in data.items():
            setattr(existing, k, v)
        record = existing
    session.commit()
    return record


def load_all_profiles(directory: Path, session: Session) -> int:
    """Load every *.yaml / *.yml under directory. Returns count loaded."""
    count = 0
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        upsert_profile(path, session)
        count += 1
    return count
