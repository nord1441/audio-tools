from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

APP_NAME = "audio-tools"


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False))


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def cache_dir() -> Path:
    return Path(user_cache_dir(APP_NAME, appauthor=False))


def db_path() -> Path:
    return data_dir() / "audio_tools.db"


def device_profiles_dir() -> Path:
    return config_dir() / "devices"


def playlists_dir() -> Path:
    return data_dir() / "playlists"


def models_dir() -> Path:
    return cache_dir() / "models"


def ensure_dirs() -> None:
    for d in (
        config_dir(),
        data_dir(),
        cache_dir(),
        device_profiles_dir(),
        playlists_dir(),
        models_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)
