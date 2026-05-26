from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "audio-tools"


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False))


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def db_path() -> Path:
    return data_dir() / "audio_tools.db"


def device_profiles_dir() -> Path:
    return config_dir() / "devices"


def playlists_dir() -> Path:
    return data_dir() / "playlists"


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), device_profiles_dir(), playlists_dir()):
        d.mkdir(parents=True, exist_ok=True)
