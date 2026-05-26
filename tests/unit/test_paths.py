from pathlib import Path
from audio_tools import paths


def test_config_dir_under_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.config_dir() == tmp_path / "audio-tools"


def test_data_dir_under_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path / "audio-tools"


def test_db_path_lives_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.db_path() == tmp_path / "audio-tools" / "audio_tools.db"


def test_device_profiles_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.device_profiles_dir() == tmp_path / "audio-tools" / "devices"


def test_playlists_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.playlists_dir() == tmp_path / "audio-tools" / "playlists"


def test_ensure_dirs_creates_them(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    paths.ensure_dirs()
    assert paths.config_dir().is_dir()
    assert paths.data_dir().is_dir()
    assert paths.device_profiles_dir().is_dir()
    assert paths.playlists_dir().is_dir()


def test_models_dir_under_xdg_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert paths.models_dir() == tmp_path / "audio-tools" / "models"


def test_ensure_dirs_creates_models_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    paths.ensure_dirs()
    assert paths.models_dir().is_dir()
