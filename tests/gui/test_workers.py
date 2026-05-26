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


import os


def _seed_tracks(factory, music):
    from audio_tools.core import scanner
    with factory() as s:
        scanner.scan(music, s)


def test_analyze_worker_with_fake_backend(qtbot, tmp_path, session_factory_from, monkeypatch):
    _ensure_fixtures()
    factory, _engine = session_factory_from
    music = tmp_path / "music"; music.mkdir()
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
    _seed_tracks(factory, music)

    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")

    from audio_tools.gui.workers import AnalyzeWorker

    worker = AnalyzeWorker(session_factory=factory, backend_name="fake")
    with qtbot.waitSignal(worker.signals.finished, timeout=15_000) as blocker:
        QThreadPool.globalInstance().start(worker)
    result = blocker.args[0]
    assert getattr(result, "analyzed", 0) == 1


def test_cluster_worker_force_refit(qtbot, tmp_path, session_factory_from, monkeypatch):
    _ensure_fixtures()
    factory, _engine = session_factory_from
    music = tmp_path / "music"; music.mkdir()
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        shutil.copy(FIXTURE_MP3, music / name)
    _seed_tracks(factory, music)

    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    from audio_tools.gui.workers import AnalyzeWorker, ClusterWorker

    aw = AnalyzeWorker(session_factory=factory, backend_name="fake")
    with qtbot.waitSignal(aw.signals.finished, timeout=15_000):
        QThreadPool.globalInstance().start(aw)

    cw = ClusterWorker(session_factory=factory, k=2, force=True, incremental=False)
    with qtbot.waitSignal(cw.signals.finished, timeout=10_000) as blocker:
        QThreadPool.globalInstance().start(cw)
    summary = blocker.args[0]
    assert summary["assigned"] == 3 or summary["mode"] == "refit"


def test_playlists_worker_writes_files(qtbot, tmp_path, session_factory_from, monkeypatch):
    _ensure_fixtures()
    factory, _engine = session_factory_from
    music = tmp_path / "music"; music.mkdir()
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        shutil.copy(FIXTURE_MP3, music / name)
    _seed_tracks(factory, music)

    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    from audio_tools.gui.workers import AnalyzeWorker, ClusterWorker, PlaylistsWorker

    for w in (
        AnalyzeWorker(session_factory=factory, backend_name="fake"),
        ClusterWorker(session_factory=factory, k=2, force=True, incremental=False),
    ):
        with qtbot.waitSignal(w.signals.finished, timeout=15_000):
            QThreadPool.globalInstance().start(w)

    out_dir = tmp_path / "plists"
    pw = PlaylistsWorker(session_factory=factory, out_dir=out_dir)
    with qtbot.waitSignal(pw.signals.finished, timeout=10_000) as blocker:
        QThreadPool.globalInstance().start(pw)
    written = blocker.args[0]
    assert isinstance(written, list)
    assert len(written) >= 1


def test_transfer_worker_with_fake_runner(qtbot, tmp_path, session_factory_from, monkeypatch):
    _ensure_fixtures()
    factory, _engine = session_factory_from
    music = tmp_path / "music"; music.mkdir()
    for name in ("a.mp3", "b.mp3"):  # need >= k=2 tracks for clustering
        shutil.copy(FIXTURE_MP3, music / name)
    _seed_tracks(factory, music)

    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND", "1")
    monkeypatch.setenv("AUDIO_TOOLS_ALLOW_FAKE_FFMPEG", "1")

    from audio_tools.gui.workers import AnalyzeWorker, ClusterWorker, TransferWorker
    from audio_tools.core import device_profile as dp_mod

    for w in (
        AnalyzeWorker(session_factory=factory, backend_name="fake"),
        ClusterWorker(session_factory=factory, k=2, force=True, incremental=False),
    ):
        with qtbot.waitSignal(w.signals.finished, timeout=15_000):
            QThreadPool.globalInstance().start(w)

    profiles_dir = tmp_path / "profs"; profiles_dir.mkdir()
    (profiles_dir / "p.yaml").write_text(
        "name: p\ncodec: opus\ncontainer: ogg\n"
        "max_bitrate: 96\nmin_bitrate: 64\nbitrate_step: 32\n"
        "max_size_bytes: 100000000\nsample_rate_max: 48000\n"
        "m3u_path_style: relative\nfolder_layout: \"{title}\"\n"
    )
    with factory() as s:
        dp_mod.upsert_profile(profiles_dir / "p.yaml", s)

    target_dir = tmp_path / "device"; target_dir.mkdir()
    tw = TransferWorker(
        session_factory=factory,
        profile_name="p",
        playlists=["Cluster 1"],
        target_dir=target_dir,
        ffmpeg_backend="fake",
        workers_count=1,
    )
    with qtbot.waitSignal(tw.signals.finished, timeout=30_000) as blocker:
        QThreadPool.globalInstance().start(tw)
    outcome = blocker.args[0]
    assert hasattr(outcome, "copied")
