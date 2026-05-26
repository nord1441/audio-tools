import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool


FIXTURE_MP3 = Path(__file__).parent.parent / "fixtures" / "audio" / "test_tagged.mp3"


def _ensure_fixtures():
    if not FIXTURE_MP3.exists():
        import subprocess
        subprocess.run(
            ["bash", str(FIXTURE_MP3.parent.parent / "generate_audio_fixtures.sh")],
            check=True,
        )


def test_scan_worker_emits_finished_with_result(qtbot, tmp_path, session_factory_from):
    _ensure_fixtures()
    factory, _engine = session_factory_from
    music = tmp_path / "music"; music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    shutil.copy(FIXTURE_MP3, music / "b.mp3")

    from audio_tools.gui.workers import ScanWorker

    worker = ScanWorker(session_factory=factory, root=music)
    with qtbot.waitSignal(worker.signals.finished, timeout=15_000) as blocker:
        QThreadPool.globalInstance().start(worker)
    result = blocker.args[0]
    assert getattr(result, "added", None) == 2


def test_scan_worker_emits_error_when_root_missing(qtbot, tmp_path, session_factory_from):
    factory, _engine = session_factory_from

    from audio_tools.gui.workers import ScanWorker

    worker = ScanWorker(session_factory=factory, root=tmp_path / "nope")
    with qtbot.waitSignal(worker.signals.error, timeout=5_000) as blocker:
        QThreadPool.globalInstance().start(worker)
    assert "nope" in blocker.args[0] or "not" in blocker.args[0].lower()
