import shutil
from pathlib import Path

from click.testing import CliRunner

from audio_tools.cli import main

FIXTURE_MP3 = Path(__file__).parent.parent / "fixtures" / "audio" / "test_tagged.mp3"


def _ensure_fixtures():
    if not FIXTURE_MP3.exists():
        import subprocess
        subprocess.run(
            ["bash", str(FIXTURE_MP3.parent.parent / "generate_audio_fixtures.sh")],
            check=True,
        )


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_scan_reports_results(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    shutil.copy(FIXTURE_MP3, music / "b.mp3")

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")

    runner = CliRunner()
    # Initialize schema first (mimics `alembic upgrade head` for tests)
    from audio_tools.core.db import Base, make_engine
    engine = make_engine(db)
    Base.metadata.create_all(engine)

    result = runner.invoke(main, ["scan", str(music)])
    assert result.exit_code == 0, result.output
    assert "added=2" in result.output


def test_cli_scan_errors_when_dir_missing(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    runner = CliRunner()
    result = runner.invoke(main, ["scan", str(tmp_path / "does_not_exist")])
    assert result.exit_code != 0
    assert "does not exist" in result.output.lower() or "no such" in result.output.lower()


def test_cli_fetch_models_writes_files(tmp_path, monkeypatch):
    """Stub the downloader and assert files land in models_dir()."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    import audio_tools.cli as cli_mod
    calls = []

    def fake_download(url: str, dest: Path) -> str:
        calls.append((url, dest))
        dest.write_bytes(b"FAKE_MODEL")
        import hashlib
        return hashlib.sha256(b"FAKE_MODEL").hexdigest()

    monkeypatch.setattr(cli_mod, "_download_to_file", fake_download)

    runner = CliRunner()
    result = runner.invoke(main, ["fetch-models"])
    assert result.exit_code == 0, result.output

    from audio_tools.core.model_registry import EXPECTED_MODELS
    from audio_tools.paths import models_dir
    for m in EXPECTED_MODELS:
        assert (models_dir() / m.filename).exists()
    assert len(calls) == len(EXPECTED_MODELS)


def test_cli_fetch_models_skips_existing(tmp_path, monkeypatch):
    """If a file already exists with no hash to verify, fetch-models leaves it."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    from audio_tools.paths import models_dir
    from audio_tools.core.model_registry import EXPECTED_MODELS
    md = models_dir()
    md.mkdir(parents=True, exist_ok=True)
    for m in EXPECTED_MODELS:
        (md / m.filename).write_bytes(b"already here")

    import audio_tools.cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_download_to_file",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not download")),
    )

    runner = CliRunner()
    result = runner.invoke(main, ["fetch-models"])
    assert result.exit_code == 0
    assert "already present" in result.output.lower() or "skip" in result.output.lower()


def test_cli_analyze_with_fake_backend(tmp_path, monkeypatch):
    """`audio-tools analyze --backend=fake` should populate features."""
    _ensure_fixtures()
    music = tmp_path / "music"
    music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    shutil.copy(FIXTURE_MP3, music / "b.mp3")

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")

    from audio_tools.core.db import Base, make_engine
    engine = make_engine(db)
    Base.metadata.create_all(engine)

    runner = CliRunner()
    # Scan first to populate tracks.
    assert runner.invoke(main, ["scan", str(music)]).exit_code == 0
    result = runner.invoke(main, ["analyze", "--backend=fake"])
    assert result.exit_code == 0, result.output
    assert "analyzed=2" in result.output


def test_cli_analyze_refuses_fake_without_env_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", raising=False)
    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "--backend=fake"])
    assert result.exit_code != 0
    assert "ALLOW_FAKE" in result.output or "fake backend" in result.output.lower()


def test_cli_cluster_initial_uses_default_k(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"; music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    shutil.copy(FIXTURE_MP3, music / "b.mp3")
    shutil.copy(FIXTURE_MP3, music / "c.mp3")

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    runner = CliRunner()
    assert runner.invoke(main, ["scan", str(music)]).exit_code == 0
    assert runner.invoke(main, ["analyze", "--backend=fake"]).exit_code == 0
    result = runner.invoke(main, ["cluster", "--k=2", "--force"])
    assert result.exit_code == 0, result.output
    assert "clusters=2" in result.output


def test_cli_cluster_incremental_when_clusters_exist(tmp_path, monkeypatch):
    _ensure_fixtures()
    music = tmp_path / "music"; music.mkdir()
    for n in ("a.mp3", "b.mp3", "c.mp3", "d.mp3"):
        shutil.copy(FIXTURE_MP3, music / n)

    db = tmp_path / "test.db"
    monkeypatch.setenv("AUDIO_TOOLS_DB_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    from audio_tools.core.db import Base, make_engine
    Base.metadata.create_all(make_engine(db))

    runner = CliRunner()
    runner.invoke(main, ["scan", str(music)])
    runner.invoke(main, ["analyze", "--backend=fake"])
    runner.invoke(main, ["cluster", "--k=2", "--force"])

    # Add a new track, re-scan, re-analyze, then cluster with no args → incremental
    shutil.copy(FIXTURE_MP3, music / "new.mp3")
    runner.invoke(main, ["scan", str(music)])
    runner.invoke(main, ["analyze", "--backend=fake"])
    result = runner.invoke(main, ["cluster"])
    assert result.exit_code == 0, result.output
    assert "assigned=1" in result.output
