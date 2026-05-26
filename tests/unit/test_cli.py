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
