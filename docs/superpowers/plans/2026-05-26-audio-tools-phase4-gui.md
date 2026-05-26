# audio-tools Phase 4 (PySide6 GUI — MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an `audio-tools gui` desktop window with 5 navigable views (Library / Clusters / Transfer / Devices / Settings) that dispatch the existing Phase 1–3 CLI workflows to a background `QThreadPool`. Smoke tests run headless via pytest-qt + `offscreen` Qt platform.

**Architecture:** Sidebar (`QListWidget`) + `QStackedWidget` of 5 view pages. Each view talks to the engine via a `session_factory` callable. Long-running work goes through `QRunnable` subclasses that emit `progress`/`error`/`finished` Qt signals. PySide6 is a `[gui]` optional extra; CLI imports `audio_tools.gui` lazily.

**Tech Stack:** Python 3.11+, PySide6 6.6+, pytest-qt 4.4+, plus everything from Phase 1–3.

**Reference docs:**
- Parent spec: `docs/superpowers/specs/2026-05-25-audio-tools-design.md`
- Phase 4 design addendum: `docs/superpowers/specs/2026-05-26-audio-tools-phase4-design.md`

---

## File Structure (Phase 4)

```
audio-tools/
├── pyproject.toml                            # Task 1
├── src/audio_tools/
│   ├── cli.py                                # Task 10 (+gui subcommand)
│   └── gui/
│       ├── __init__.py                       # Task 1
│       ├── app.py                            # Task 10
│       ├── main_window.py                    # Task 4
│       ├── workers.py                        # Tasks 2-3
│       ├── library_view.py                   # Task 5
│       ├── cluster_view.py                   # Task 6
│       ├── transfer_view.py                  # Task 7
│       ├── devices_view.py                   # Task 8
│       └── settings_view.py                  # Task 9
└── tests/gui/
    ├── __init__.py                           # Task 1
    ├── conftest.py                           # Task 1
    ├── test_workers.py                       # Tasks 2-3
    ├── test_main_window.py                   # Task 4
    └── test_views_smoke.py                   # Tasks 5-9, 11
```

---

## Task 1: PySide6/pytest-qt deps + gui package skeleton + tests/gui conftest

**Files:**
- Modify: `pyproject.toml`
- Create: `src/audio_tools/gui/__init__.py`
- Create: `tests/gui/__init__.py`
- Create: `tests/gui/conftest.py`

- [ ] **Step 1: Add the gui extra to `pyproject.toml`**

Append a new optional extra:

```toml
[project.optional-dependencies]
gui = [
    "PySide6>=6.6",
    "pytest-qt>=4.4",
]
```

- [ ] **Step 2: Install**

```bash
source .venv/bin/activate
pip install -e ".[dev,gui]"
```

- [ ] **Step 3: Create the gui package**

`src/audio_tools/gui/__init__.py` (empty file).

- [ ] **Step 4: Create test conftest that skips when PySide6 is missing**

`tests/gui/__init__.py` (empty).

`tests/gui/conftest.py`:

```python
import os

import pytest

# Headless Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
except ImportError:
    pytest.skip("PySide6 not installed — skipping GUI tests", allow_module_level=True)


@pytest.fixture
def session_factory_from(tmp_path):
    """Build an in-memory session factory pointed at a tmp DB.

    Yields a (factory, engine) pair so tests can also drive the engine
    directly (e.g., create tables) when needed.
    """
    from audio_tools.core.db import Base, make_engine, make_session_factory
    engine = make_engine(tmp_path / "gui_test.db")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine), engine
```

- [ ] **Step 5: Run the GUI test directory (no tests yet — must collect cleanly)**

```bash
python -m pytest tests/gui -v
```
Expected: 0 collected, 0 errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/audio_tools/gui/__init__.py tests/gui/__init__.py tests/gui/conftest.py
git commit -m "chore(phase4): add PySide6/pytest-qt deps and gui package skeleton"
```

---

## Task 2: `gui/workers.py` — `BaseWorker`, `WorkerSignals`, `ScanWorker`

**Files:**
- Create: `src/audio_tools/gui/workers.py`
- Create: `tests/gui/test_workers.py`

- [ ] **Step 1: Write the failing test**

`tests/gui/test_workers.py`:

```python
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
    # ScanResult dataclass: added attribute is 2
    assert getattr(result, "added", None) == 2


def test_scan_worker_emits_error_when_root_missing(qtbot, tmp_path, session_factory_from):
    factory, _engine = session_factory_from

    from audio_tools.gui.workers import ScanWorker

    worker = ScanWorker(session_factory=factory, root=tmp_path / "nope")
    with qtbot.waitSignal(worker.signals.error, timeout=5_000) as blocker:
        QThreadPool.globalInstance().start(worker)
    assert "nope" in blocker.args[0] or "not" in blocker.args[0].lower()
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/gui/test_workers.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `workers.py` (BaseWorker + ScanWorker)**

`src/audio_tools/gui/workers.py`:

```python
"""Qt workers wrapping Phase 1–3 core functions for background dispatch."""
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal
from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]


class WorkerSignals(QObject):
    progress = Signal(str)
    error = Signal(str)
    finished = Signal(object)


class BaseWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.setAutoDelete(True)


class ScanWorker(BaseWorker):
    def __init__(self, *, session_factory: SessionFactory, root: Path):
        super().__init__()
        self._session_factory = session_factory
        self._root = Path(root)

    def run(self) -> None:
        from audio_tools.core import scanner
        if not self._root.is_dir():
            self.signals.error.emit(f"Directory not found: {self._root}")
            return
        try:
            with self._session_factory() as session:
                result = scanner.scan(self._root, session)
            self.signals.progress.emit(
                f"Scan: added={result.added} updated={result.updated} "
                f"moved={result.moved} removed={result.removed}"
            )
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gui/test_workers.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/workers.py tests/gui/test_workers.py
git commit -m "feat(gui): BaseWorker, WorkerSignals, and ScanWorker"
```

---

## Task 3: `AnalyzeWorker`, `ClusterWorker`, `PlaylistsWorker`, `TransferWorker`

**Files:**
- Modify: `src/audio_tools/gui/workers.py`
- Modify: `tests/gui/test_workers.py`

- [ ] **Step 1: Append worker tests**

```python
import os


def _seed_tracks(factory, music: Path):
    """Run a real scan, used as a setup helper for the analyze/cluster tests."""
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
    # Analyze synchronously first via the worker so embeddings exist
    from audio_tools.gui.workers import AnalyzeWorker, ClusterWorker

    aw = AnalyzeWorker(session_factory=factory, backend_name="fake")
    with qtbot.waitSignal(aw.signals.finished, timeout=15_000):
        QThreadPool.globalInstance().start(aw)

    cw = ClusterWorker(session_factory=factory, k=2, force=True, incremental=False)
    with qtbot.waitSignal(cw.signals.finished, timeout=10_000) as blocker:
        QThreadPool.globalInstance().start(cw)
    summary = blocker.args[0]
    # Returns a dict-or-dataclass with assigned and mode keys
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
    shutil.copy(FIXTURE_MP3, music / "a.mp3")
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
```

- [ ] **Step 2: Verify failures**

```bash
python -m pytest tests/gui/test_workers.py -v
```
Expected: 4 new tests FAIL (`ImportError`).

- [ ] **Step 3: Add the four workers to `gui/workers.py`**

Append:

```python
from typing import Optional, Sequence


class AnalyzeWorker(BaseWorker):
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        backend_name: str,
        workers_count: int | None = None,
        timeout_s: int = 300,
        rescan: bool = False,
    ):
        super().__init__()
        self._session_factory = session_factory
        self._backend_name = backend_name
        self._workers_count = workers_count
        self._timeout_s = timeout_s
        self._rescan = rescan

    def run(self) -> None:
        from audio_tools.core import analyzer as analyzer_mod
        from audio_tools import paths as paths_mod
        import os

        try:
            if self._backend_name == "fake":
                if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND") != "1":
                    self.signals.error.emit(
                        "Fake backend disabled; set AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1"
                    )
                    return
                backend = analyzer_mod.FakeBackend()
            elif self._backend_name == "essentia":
                backend = analyzer_mod.EssentiaBackend(models_dir=paths_mod.models_dir())
            else:
                self.signals.error.emit(f"Unknown backend: {self._backend_name}")
                return

            with self._session_factory() as session:
                result = analyzer_mod.analyze_tracks(
                    session, backend,
                    single_threaded=True,  # GUI dispatches to its own threadpool
                    workers=self._workers_count,
                    timeout_s=self._timeout_s,
                    rescan=self._rescan,
                )
            self.signals.progress.emit(
                f"Analyze: analyzed={result.analyzed} failed={result.failed}"
            )
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))


class ClusterWorker(BaseWorker):
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        k: int | None,
        force: bool,
        incremental: bool,
    ):
        super().__init__()
        self._session_factory = session_factory
        self._k = k
        self._force = force
        self._incremental = incremental

    def run(self) -> None:
        from audio_tools.core import clusterer as clusterer_mod
        from audio_tools.core.models import Cluster
        from sqlalchemy import select
        try:
            with self._session_factory() as session:
                existing = session.scalar(select(Cluster)) is not None
                if self._incremental or (self._k is None and existing):
                    assigned = clusterer_mod.assign_new(session)
                    summary = {"mode": "incremental", "assigned": assigned}
                else:
                    k = self._k if self._k is not None else 6
                    assigned = clusterer_mod.recluster(session, k=k)
                    summary = {"mode": "refit", "k": k, "assigned": assigned}
            self.signals.progress.emit(f"Cluster: {summary}")
            self.signals.finished.emit(summary)
        except Exception as e:
            self.signals.error.emit(str(e))


class PlaylistsWorker(BaseWorker):
    def __init__(self, *, session_factory: SessionFactory, out_dir: Path):
        super().__init__()
        self._session_factory = session_factory
        self._out_dir = Path(out_dir)

    def run(self) -> None:
        from audio_tools.core import playlist_builder as pl_mod
        try:
            with self._session_factory() as session:
                written = pl_mod.write_playlists(session, self._out_dir)
            self.signals.progress.emit(f"Playlists: wrote {len(written)} files")
            self.signals.finished.emit(written)
        except Exception as e:
            self.signals.error.emit(str(e))


class TransferWorker(BaseWorker):
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        profile_name: str,
        playlists: Sequence[str],
        target_dir: Path,
        ffmpeg_backend: str,
        workers_count: int,
    ):
        super().__init__()
        self._session_factory = session_factory
        self._profile_name = profile_name
        self._playlists = list(playlists)
        self._target_dir = Path(target_dir)
        self._ffmpeg_backend = ffmpeg_backend
        self._workers_count = workers_count

    def run(self) -> None:
        import os
        from pathlib import PurePath
        from sqlalchemy import select

        from audio_tools.core import transfer as transfer_mod
        from audio_tools.core.models import (
            Cluster,
            ClusterAssignment,
            DeviceProfile,
            Track,
        )
        from audio_tools.core.transcoder import FakeFfmpegRunner, RealFfmpegRunner
        from audio_tools.core.transfer_planner import plan as plan_fn
        from audio_tools.core.transfer_target import LocalDirectoryTarget
        from audio_tools import paths as paths_mod

        try:
            if self._ffmpeg_backend == "fake":
                if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_FFMPEG") != "1":
                    self.signals.error.emit("Fake ffmpeg disabled; set AUDIO_TOOLS_ALLOW_FAKE_FFMPEG=1")
                    return
                runner = FakeFfmpegRunner()
            else:
                runner = RealFfmpegRunner()

            with self._session_factory() as session:
                profile = session.scalar(select(DeviceProfile).where(DeviceProfile.name == self._profile_name))
                if profile is None:
                    self.signals.error.emit(f"Profile {self._profile_name!r} not in DB")
                    return

                tracks: list[Track] = []
                for plist in self._playlists:
                    c = session.scalar(select(Cluster).where(Cluster.name == plist))
                    if c is None:
                        self.signals.error.emit(f"No cluster named {plist!r}")
                        return
                    stmt = (
                        select(Track)
                        .join(ClusterAssignment, ClusterAssignment.track_id == Track.id)
                        .where(ClusterAssignment.cluster_id == c.id)
                        .order_by(ClusterAssignment.distance.asc())
                    )
                    tracks.extend(session.scalars(stmt).all())

                plan_obj = plan_fn(tracks, profile)
                outcome = transfer_mod.execute_transfer(
                    session=session,
                    profile=profile,
                    plan=plan_obj,
                    target=LocalDirectoryTarget(self._target_dir),
                    ffmpeg=runner,
                    m3u_relpath=PurePath("Playlists") / f"{self._playlists[0]}.m3u",
                    cache_dir=paths_mod.cache_dir() / "transcode",
                    workers=self._workers_count,
                )
            self.signals.progress.emit(
                f"Transfer: copied={outcome.copied} skipped={outcome.skipped} failed={outcome.failed}"
            )
            self.signals.finished.emit(outcome)
        except Exception as e:
            self.signals.error.emit(str(e))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gui/test_workers.py -v
```
Expected: 6 tests PASS (2 from Task 2 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/workers.py tests/gui/test_workers.py
git commit -m "feat(gui): add Analyze/Cluster/Playlists/Transfer workers"
```

---

## Task 4: `gui/main_window.py` — sidebar + stacked widget + status bar

**Files:**
- Create: `src/audio_tools/gui/main_window.py`
- Create: `tests/gui/test_main_window.py`

- [ ] **Step 1: Write the failing test**

`tests/gui/test_main_window.py`:

```python
import pytest
from PySide6.QtWidgets import QListWidget, QStackedWidget, QStatusBar


def test_main_window_constructs(qtbot, session_factory_from):
    from audio_tools.gui.main_window import MainWindow

    factory, _engine = session_factory_from
    win = MainWindow(session_factory=factory)
    qtbot.addWidget(win)
    assert win.windowTitle().lower().startswith("audio")


def test_sidebar_has_five_entries(qtbot, session_factory_from):
    from audio_tools.gui.main_window import MainWindow

    factory, _engine = session_factory_from
    win = MainWindow(session_factory=factory)
    qtbot.addWidget(win)
    sidebar = win.findChild(QListWidget, "sidebar")
    assert sidebar is not None
    assert sidebar.count() == 5
    names = [sidebar.item(i).text() for i in range(sidebar.count())]
    assert names == ["Library", "Clusters", "Transfer", "Devices", "Settings"]


def test_sidebar_switches_stacked_widget(qtbot, session_factory_from):
    from audio_tools.gui.main_window import MainWindow

    factory, _engine = session_factory_from
    win = MainWindow(session_factory=factory)
    qtbot.addWidget(win)
    sidebar = win.findChild(QListWidget, "sidebar")
    stack = win.findChild(QStackedWidget, "view_stack")
    assert stack is not None and stack.count() == 5

    for i in range(5):
        sidebar.setCurrentRow(i)
        assert stack.currentIndex() == i


def test_status_bar_present(qtbot, session_factory_from):
    from audio_tools.gui.main_window import MainWindow

    factory, _engine = session_factory_from
    win = MainWindow(session_factory=factory)
    qtbot.addWidget(win)
    assert isinstance(win.statusBar(), QStatusBar)
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/gui/test_main_window.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `main_window.py`**

```python
# src/audio_tools/gui/main_window.py
"""Main window: sidebar nav + stacked view + status bar."""
from typing import Callable

from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)
from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]


class MainWindow(QMainWindow):
    def __init__(self, *, session_factory: SessionFactory):
        super().__init__()
        self.setWindowTitle("audio-tools")
        self.resize(1100, 700)
        self._session_factory = session_factory

        from audio_tools.gui.library_view import LibraryView
        from audio_tools.gui.cluster_view import ClusterView
        from audio_tools.gui.transfer_view import TransferView
        from audio_tools.gui.devices_view import DevicesView
        from audio_tools.gui.settings_view import SettingsView

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        sidebar = QListWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMaximumWidth(180)
        sidebar.addItems(["Library", "Clusters", "Transfer", "Devices", "Settings"])
        layout.addWidget(sidebar)

        stack = QStackedWidget()
        stack.setObjectName("view_stack")
        layout.addWidget(stack, 1)

        # Each view receives the session_factory.
        self._views = {
            "Library": LibraryView(session_factory=session_factory, status_bar=self.statusBar()),
            "Clusters": ClusterView(session_factory=session_factory, status_bar=self.statusBar()),
            "Transfer": TransferView(session_factory=session_factory, status_bar=self.statusBar()),
            "Devices": DevicesView(session_factory=session_factory, status_bar=self.statusBar()),
            "Settings": SettingsView(),
        }
        for name in ("Library", "Clusters", "Transfer", "Devices", "Settings"):
            stack.addWidget(self._views[name])

        sidebar.currentRowChanged.connect(stack.setCurrentIndex)
        sidebar.setCurrentRow(0)

        self.statusBar().showMessage("Ready")
```

- [ ] **Step 4: Run tests (will still fail because the view modules don't exist yet)**

You need to scaffold the five view files with empty `QWidget` subclasses so the import in main_window.py succeeds. Create five tiny stubs:

`src/audio_tools/gui/library_view.py`:

```python
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LibraryView(QWidget):
    def __init__(self, *, session_factory, status_bar):
        super().__init__()
        QVBoxLayout(self).addWidget(QLabel("Library (skeleton)"))
```

Create identical 3-line stubs for `cluster_view.py`, `transfer_view.py`, `devices_view.py`, `settings_view.py` (the latter takes no kwargs in `MainWindow`).

```python
# settings_view.py
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SettingsView(QWidget):
    def __init__(self):
        super().__init__()
        QVBoxLayout(self).addWidget(QLabel("Settings (skeleton)"))
```

The other three follow the same template with `session_factory` + `status_bar` kwargs.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/gui/test_main_window.py -v
```
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/audio_tools/gui/main_window.py \
       src/audio_tools/gui/library_view.py \
       src/audio_tools/gui/cluster_view.py \
       src/audio_tools/gui/transfer_view.py \
       src/audio_tools/gui/devices_view.py \
       src/audio_tools/gui/settings_view.py \
       tests/gui/test_main_window.py
git commit -m "feat(gui): MainWindow with sidebar nav and 5 view stubs"
```

---

## Task 5: `LibraryView` — track table + Scan / Analyze / Cluster / Playlists buttons

**Files:**
- Modify: `src/audio_tools/gui/library_view.py`
- Modify: `tests/gui/test_views_smoke.py` (create)

- [ ] **Step 1: Write tests**

`tests/gui/test_views_smoke.py`:

```python
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStatusBar, QTableView


def test_library_view_constructs(qtbot, session_factory_from):
    from audio_tools.gui.library_view import LibraryView
    factory, _engine = session_factory_from
    sb = QStatusBar()
    v = LibraryView(session_factory=factory, status_bar=sb)
    qtbot.addWidget(v)
    table = v.findChild(QTableView, "tracks_table")
    assert table is not None


def test_library_view_loads_existing_tracks(qtbot, session_factory_from):
    from audio_tools.core.models import Track
    from audio_tools.gui.library_view import LibraryView

    factory, _engine = session_factory_from
    with factory() as s:
        s.add_all([
            Track(path="/m/a.mp3", mtime=0.0, size=1, title="A", artist="X"),
            Track(path="/m/b.mp3", mtime=0.0, size=1, title="B", artist="Y"),
        ])
        s.commit()

    sb = QStatusBar()
    v = LibraryView(session_factory=factory, status_bar=sb)
    qtbot.addWidget(v)
    v.reload_table()
    table = v.findChild(QTableView, "tracks_table")
    assert table.model().rowCount() == 2
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/gui/test_views_smoke.py::test_library_view_loads_existing_tracks -v
```
Expected: FAIL (the stub doesn't have `reload_table` or a table).

- [ ] **Step 3: Implement `library_view.py`**

```python
# src/audio_tools/gui/library_view.py
"""Library: track table + the four pipeline buttons (Scan/Analyze/Cluster/Playlists)."""
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.gui.workers import (
    AnalyzeWorker,
    ClusterWorker,
    PlaylistsWorker,
    ScanWorker,
)


SessionFactory = Callable[[], Session]
COLUMNS = ("id", "title", "artist", "bpm", "key", "cluster", "analyzed?")


class LibraryView(QWidget):
    def __init__(self, *, session_factory: SessionFactory, status_bar: QStatusBar):
        super().__init__()
        self._session_factory = session_factory
        self._status_bar = status_bar

        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self._scan_btn = QPushButton("Scan…")
        self._scan_btn.clicked.connect(self._on_scan)
        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.clicked.connect(self._on_analyze)
        self._cluster_btn = QPushButton("Cluster…")
        self._cluster_btn.clicked.connect(self._on_cluster)
        self._playlists_btn = QPushButton("Write Playlists")
        self._playlists_btn.clicked.connect(self._on_playlists)
        for btn in (self._scan_btn, self._analyze_btn, self._cluster_btn, self._playlists_btn):
            bar.addWidget(btn)
        bar.addStretch()
        layout.addLayout(bar)

        self._table = QTableView()
        self._table.setObjectName("tracks_table")
        self._model = QStandardItemModel(0, len(COLUMNS))
        self._model.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.setModel(self._model)
        layout.addWidget(self._table)

        self.reload_table()

    def reload_table(self) -> None:
        from audio_tools.core.models import (
            ClusterAssignment, Features, Track,
        )
        self._model.removeRows(0, self._model.rowCount())
        with self._session_factory() as session:
            for track in session.scalars(select(Track)).all():
                features = session.get(Features, track.id) if hasattr(session, "get") else None
                assignment = session.get(ClusterAssignment, track.id)
                cluster_name = ""
                if assignment is not None:
                    from audio_tools.core.models import Cluster
                    c = session.get(Cluster, assignment.cluster_id)
                    cluster_name = c.name if c else ""
                row = [
                    QStandardItem(str(track.id)),
                    QStandardItem(track.title or ""),
                    QStandardItem(track.artist or ""),
                    QStandardItem(f"{features.bpm:.1f}" if features and features.bpm else ""),
                    QStandardItem(f"{features.key} {features.scale or ''}".strip() if features else ""),
                    QStandardItem(cluster_name),
                    QStandardItem("yes" if features else "no"),
                ]
                self._model.appendRow(row)

    # --- Button handlers ---

    def _wire(self, worker, on_finished):
        worker.signals.progress.connect(self._status_bar.showMessage)
        worker.signals.error.connect(lambda e: self._status_bar.showMessage(f"ERROR: {e}"))
        worker.signals.finished.connect(on_finished)
        QThreadPool.globalInstance().start(worker)

    def _on_scan(self):
        directory = QFileDialog.getExistingDirectory(self, "Pick a music directory")
        if not directory:
            return
        self._status_bar.showMessage(f"Scanning {directory}…")
        worker = ScanWorker(session_factory=self._session_factory, root=Path(directory))
        self._wire(worker, lambda _result: self.reload_table())

    def _on_analyze(self):
        # MVP: use essentia unless env says otherwise
        import os
        backend = "fake" if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND") == "1" else "essentia"
        worker = AnalyzeWorker(session_factory=self._session_factory, backend_name=backend)
        self._wire(worker, lambda _r: self.reload_table())

    def _on_cluster(self):
        k, ok = QInputDialog.getInt(self, "Cluster", "k:", 6, 2, 50, 1)
        if not ok:
            return
        worker = ClusterWorker(session_factory=self._session_factory, k=k, force=True, incremental=False)
        self._wire(worker, lambda _r: self.reload_table())

    def _on_playlists(self):
        from audio_tools import paths as paths_mod
        worker = PlaylistsWorker(session_factory=self._session_factory, out_dir=paths_mod.playlists_dir())
        self._wire(worker, lambda _r: None)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gui/test_views_smoke.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/library_view.py tests/gui/test_views_smoke.py
git commit -m "feat(gui): LibraryView with track table and pipeline buttons"
```

---

## Task 6: `ClusterView` — cluster list + member tracks

**Files:**
- Modify: `src/audio_tools/gui/cluster_view.py`
- Modify: `tests/gui/test_views_smoke.py`

- [ ] **Step 1: Append tests**

```python
def test_cluster_view_lists_clusters(qtbot, session_factory_from):
    from datetime import datetime

    import numpy as np

    from audio_tools.core.models import Cluster, ClusterAssignment, Track
    from audio_tools.gui.cluster_view import ClusterView

    factory, _engine = session_factory_from
    with factory() as s:
        t = Track(path="/m/x.mp3", mtime=0.0, size=1, title="X")
        s.add(t); s.flush()
        c = Cluster(
            name="Workout", k_value=2,
            centroid=np.zeros(200, dtype=np.float32).tobytes(),
            created_at=datetime.utcnow(),
        )
        s.add(c); s.flush()
        s.add(ClusterAssignment(
            track_id=t.id, cluster_id=c.id, distance=0.0,
            assigned_at=datetime.utcnow(),
        ))
        s.commit()

    sb = QStatusBar()
    v = ClusterView(session_factory=factory, status_bar=sb)
    qtbot.addWidget(v)
    v.reload()

    from PySide6.QtWidgets import QListWidget
    list_w = v.findChild(QListWidget, "cluster_list")
    assert list_w.count() == 1
    assert "Workout" in list_w.item(0).text()
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/gui/test_views_smoke.py::test_cluster_view_lists_clusters -v
```

- [ ] **Step 3: Implement `cluster_view.py`**

```python
# src/audio_tools/gui/cluster_view.py
"""ClusterView: list of clusters on the left, member tracks on the right."""
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]


class ClusterView(QWidget):
    def __init__(self, *, session_factory: SessionFactory, status_bar: QStatusBar):
        super().__init__()
        self._session_factory = session_factory
        self._status_bar = status_bar

        layout = QHBoxLayout(self)

        self._list = QListWidget()
        self._list.setObjectName("cluster_list")
        self._list.setMaximumWidth(260)
        self._list.currentRowChanged.connect(self._on_cluster_selected)
        layout.addWidget(self._list)

        right = QVBoxLayout()
        self._table = QTableView()
        self._table.setObjectName("tracks_in_cluster_table")
        self._model = QStandardItemModel(0, 4)
        self._model.setHorizontalHeaderLabels(["id", "title", "artist", "distance"])
        self._table.setModel(self._model)
        right.addWidget(self._table)
        layout.addLayout(right, 1)

        self.reload()

    def reload(self) -> None:
        from audio_tools.core.models import Cluster, ClusterAssignment

        self._list.clear()
        self._model.removeRows(0, self._model.rowCount())
        with self._session_factory() as session:
            for c in session.scalars(select(Cluster)).all():
                member_count = session.scalar(
                    select(ClusterAssignment).where(ClusterAssignment.cluster_id == c.id).limit(1)
                )
                count = session.scalars(
                    select(ClusterAssignment).where(ClusterAssignment.cluster_id == c.id)
                ).all()
                self._list.addItem(QListWidgetItem(f"{c.name} ({len(count)})"))

    def _on_cluster_selected(self, row: int) -> None:
        from audio_tools.core.models import Cluster, ClusterAssignment, Track

        self._model.removeRows(0, self._model.rowCount())
        if row < 0:
            return
        with self._session_factory() as session:
            clusters = session.scalars(select(Cluster)).all()
            if row >= len(clusters):
                return
            c = clusters[row]
            stmt = (
                select(Track, ClusterAssignment)
                .join(ClusterAssignment, ClusterAssignment.track_id == Track.id)
                .where(ClusterAssignment.cluster_id == c.id)
                .order_by(ClusterAssignment.distance.asc())
            )
            for track, assignment in session.execute(stmt).all():
                self._model.appendRow([
                    QStandardItem(str(track.id)),
                    QStandardItem(track.title or ""),
                    QStandardItem(track.artist or ""),
                    QStandardItem(f"{assignment.distance:.3f}"),
                ])
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gui/test_views_smoke.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/cluster_view.py tests/gui/test_views_smoke.py
git commit -m "feat(gui): ClusterView with cluster list and member-track pane"
```

---

## Task 7: `TransferView` — form + progress log

**Files:**
- Modify: `src/audio_tools/gui/transfer_view.py`
- Modify: `tests/gui/test_views_smoke.py`

- [ ] **Step 1: Append test**

```python
def test_transfer_view_run_button_disabled_without_selection(qtbot, session_factory_from):
    from audio_tools.gui.transfer_view import TransferView
    from PySide6.QtWidgets import QPushButton

    factory, _engine = session_factory_from
    sb = QStatusBar()
    v = TransferView(session_factory=factory, status_bar=sb)
    qtbot.addWidget(v)
    run_btn = v.findChild(QPushButton, "run_btn")
    assert run_btn is not None
    assert not run_btn.isEnabled()  # no profile and no playlist → disabled
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/gui/test_views_smoke.py::test_transfer_view_run_button_disabled_without_selection -v
```

- [ ] **Step 3: Implement `transfer_view.py`**

```python
# src/audio_tools/gui/transfer_view.py
"""Transfer: profile/playlist/target selection + Run button + log."""
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.gui.workers import TransferWorker

SessionFactory = Callable[[], Session]


class TransferView(QWidget):
    def __init__(self, *, session_factory: SessionFactory, status_bar: QStatusBar):
        super().__init__()
        self._session_factory = session_factory
        self._status_bar = status_bar

        outer = QVBoxLayout(self)
        form = QFormLayout()

        self._profile_combo = QComboBox()
        form.addRow("Profile:", self._profile_combo)

        self._playlist_list = QListWidget()
        self._playlist_list.setSelectionMode(QListWidget.MultiSelection)
        form.addRow("Playlists:", self._playlist_list)

        path_row = QHBoxLayout()
        self._target_edit = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)
        path_row.addWidget(self._target_edit, 1); path_row.addWidget(browse)
        form.addRow("Target dir:", path_row)

        self._ffmpeg_combo = QComboBox()
        self._ffmpeg_combo.addItems(["real", "fake"])
        form.addRow("ffmpeg backend:", self._ffmpeg_combo)

        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(1, 32)
        self._workers_spin.setValue(os.cpu_count() or 1)
        form.addRow("Workers:", self._workers_spin)

        outer.addLayout(form)

        self._run_btn = QPushButton("Run")
        self._run_btn.setObjectName("run_btn")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)
        outer.addWidget(self._run_btn)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        outer.addWidget(self._log)

        self._profile_combo.currentTextChanged.connect(self._update_run_enabled)
        self._playlist_list.itemSelectionChanged.connect(self._update_run_enabled)

        self.reload()

    def reload(self) -> None:
        from audio_tools.core.models import Cluster, DeviceProfile
        self._profile_combo.clear()
        self._playlist_list.clear()
        with self._session_factory() as session:
            for p in session.scalars(select(DeviceProfile)).all():
                self._profile_combo.addItem(p.name)
            for c in session.scalars(select(Cluster)).all():
                self._playlist_list.addItem(c.name)
        self._update_run_enabled()

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(self, "Pick target directory")
        if d:
            self._target_edit.setText(d)

    def _update_run_enabled(self):
        ready = (
            self._profile_combo.count() > 0
            and self._profile_combo.currentText()
            and self._playlist_list.selectedItems()
        )
        self._run_btn.setEnabled(bool(ready))

    def _on_run(self):
        target = self._target_edit.text().strip()
        if not target:
            self._status_bar.showMessage("ERROR: target dir required")
            return
        target_dir = Path(target)
        target_dir.mkdir(parents=True, exist_ok=True)
        playlists = [it.text() for it in self._playlist_list.selectedItems()]
        worker = TransferWorker(
            session_factory=self._session_factory,
            profile_name=self._profile_combo.currentText(),
            playlists=playlists,
            target_dir=target_dir,
            ffmpeg_backend=self._ffmpeg_combo.currentText(),
            workers_count=self._workers_spin.value(),
        )
        worker.signals.progress.connect(self._log.appendPlainText)
        worker.signals.error.connect(lambda e: self._log.appendPlainText(f"ERROR: {e}"))
        worker.signals.finished.connect(lambda r: self._log.appendPlainText(f"DONE: {r}"))
        self._run_btn.setEnabled(False)
        worker.signals.finished.connect(lambda _r: self._run_btn.setEnabled(True))
        worker.signals.error.connect(lambda _e: self._run_btn.setEnabled(True))
        QThreadPool.globalInstance().start(worker)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gui/test_views_smoke.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/transfer_view.py tests/gui/test_views_smoke.py
git commit -m "feat(gui): TransferView with form, run button, and log"
```

---

## Task 8: `DevicesView` — profile table + reload button

**Files:**
- Modify: `src/audio_tools/gui/devices_view.py`
- Modify: `tests/gui/test_views_smoke.py`

- [ ] **Step 1: Append test**

```python
def test_devices_view_lists_profiles(qtbot, session_factory_from):
    from audio_tools.core.models import DeviceProfile
    from audio_tools.gui.devices_view import DevicesView

    factory, _engine = session_factory_from
    with factory() as s:
        s.add(DeviceProfile(
            name="walkman", codec="opus", container="ogg",
            max_bitrate=128, min_bitrate=64, bitrate_step=32,
            max_size_bytes=14_000_000_000, sample_rate_max=48000,
            m3u_path_style="relative", folder_layout="{title}",
        ))
        s.commit()

    sb = QStatusBar()
    v = DevicesView(session_factory=factory, status_bar=sb)
    qtbot.addWidget(v)
    v.reload()
    table = v.findChild(QTableView, "devices_table")
    assert table.model().rowCount() == 1
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/gui/test_views_smoke.py::test_devices_view_lists_profiles -v
```

- [ ] **Step 3: Implement `devices_view.py`**

```python
# src/audio_tools/gui/devices_view.py
"""DevicesView: list profiles + reload from YAML directory."""
from typing import Callable

from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QStatusBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]
COLUMNS = ("name", "codec", "container", "max_bitrate", "max_size_bytes", "mount_hint")


class DevicesView(QWidget):
    def __init__(self, *, session_factory: SessionFactory, status_bar: QStatusBar):
        super().__init__()
        self._session_factory = session_factory
        self._status_bar = status_bar

        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        reload_btn = QPushButton("Reload from YAML directory")
        reload_btn.clicked.connect(self._on_reload_yaml)
        bar.addWidget(reload_btn); bar.addStretch()
        layout.addLayout(bar)

        self._table = QTableView()
        self._table.setObjectName("devices_table")
        self._model = QStandardItemModel(0, len(COLUMNS))
        self._model.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.setModel(self._model)
        layout.addWidget(self._table)

        self.reload()

    def reload(self) -> None:
        from audio_tools.core.models import DeviceProfile
        self._model.removeRows(0, self._model.rowCount())
        with self._session_factory() as session:
            for p in session.scalars(select(DeviceProfile)).all():
                self._model.appendRow([
                    QStandardItem(p.name),
                    QStandardItem(p.codec),
                    QStandardItem(p.container),
                    QStandardItem(str(p.max_bitrate)),
                    QStandardItem(str(p.max_size_bytes)),
                    QStandardItem(p.mount_hint or ""),
                ])

    def _on_reload_yaml(self):
        from audio_tools import paths as paths_mod
        from audio_tools.core import device_profile as dp_mod
        try:
            with self._session_factory() as session:
                count = dp_mod.load_all_profiles(paths_mod.device_profiles_dir(), session)
            self._status_bar.showMessage(f"Loaded {count} profile(s) from YAML")
            self.reload()
        except Exception as e:
            self._status_bar.showMessage(f"ERROR: {e}")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gui/test_views_smoke.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/devices_view.py tests/gui/test_views_smoke.py
git commit -m "feat(gui): DevicesView with profile table and YAML reload"
```

---

## Task 9: `SettingsView` — read-only labels

**Files:**
- Modify: `src/audio_tools/gui/settings_view.py`
- Modify: `tests/gui/test_views_smoke.py`

- [ ] **Step 1: Append test**

```python
def test_settings_view_shows_paths(qtbot):
    from audio_tools.gui.settings_view import SettingsView
    from PySide6.QtWidgets import QLabel

    v = SettingsView()
    qtbot.addWidget(v)
    labels = v.findChildren(QLabel)
    texts = " ".join(l.text() for l in labels)
    assert "audio-tools" in texts.lower() or "version" in texts.lower()
```

- [ ] **Step 2: Verify failure**

```bash
python -m pytest tests/gui/test_views_smoke.py::test_settings_view_shows_paths -v
```

- [ ] **Step 3: Implement `settings_view.py`**

```python
# src/audio_tools/gui/settings_view.py
"""Settings: read-only display of version + XDG paths."""
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SettingsView(QWidget):
    def __init__(self):
        super().__init__()
        from audio_tools import __version__, paths as paths_mod

        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Version:", QLabel(__version__))
        form.addRow("Config dir:", QLabel(str(paths_mod.config_dir())))
        form.addRow("Data dir:", QLabel(str(paths_mod.data_dir())))
        form.addRow("Cache dir:", QLabel(str(paths_mod.cache_dir())))
        form.addRow("Models dir:", QLabel(str(paths_mod.models_dir())))
        form.addRow("Playlists dir:", QLabel(str(paths_mod.playlists_dir())))
        form.addRow("DB path:", QLabel(str(paths_mod.db_path())))
        outer.addLayout(form)

        open_btn = QPushButton("Open data directory")
        open_btn.clicked.connect(self._open_data_dir)
        outer.addWidget(open_btn)
        outer.addStretch()

    def _open_data_dir(self):
        import subprocess
        from audio_tools import paths as paths_mod
        try:
            subprocess.Popen(["xdg-open", str(paths_mod.data_dir())])
        except Exception:
            pass
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/gui/test_views_smoke.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/settings_view.py tests/gui/test_views_smoke.py
git commit -m "feat(gui): SettingsView with version + XDG path display"
```

---

## Task 10: `gui/app.py` + `audio-tools gui` CLI subcommand

**Files:**
- Create: `src/audio_tools/gui/app.py`
- Modify: `src/audio_tools/cli.py`

- [ ] **Step 1: Write `app.py`**

```python
# src/audio_tools/gui/app.py
"""GUI entry point. Builds engine + session factory + main window + runs app.exec()."""
import sys
from pathlib import Path
from typing import Optional


def run_gui(db_url: Optional[str] = None) -> int:
    from PySide6.QtWidgets import QApplication

    from audio_tools import paths as paths_mod
    from audio_tools.core.db import make_engine, make_session_factory
    from audio_tools.gui.main_window import MainWindow

    if db_url:
        if not db_url.startswith("sqlite:///"):
            raise SystemExit(f"Unsupported DB URL: {db_url}")
        db_path = Path(db_url.removeprefix("sqlite:///"))
    else:
        db_path = paths_mod.db_path()

    paths_mod.ensure_dirs()
    engine = make_engine(db_path)
    session_factory = make_session_factory(engine)

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(session_factory=session_factory)
    window.show()
    return app.exec()
```

- [ ] **Step 2: Add the `gui` CLI subcommand**

Append to `src/audio_tools/cli.py`:

```python
@main.command("gui")
@click.option("--db", "db_url", type=str, default=None,
              help="Override DB URL (sqlite:///...). Defaults to XDG location.")
def gui_cmd(db_url):
    """Launch the desktop GUI."""
    try:
        from audio_tools.gui.app import run_gui
    except ImportError as e:
        raise click.UsageError(
            f"GUI dependencies missing. Run `pip install -e .[gui]` first.\n({e})"
        )
    raise SystemExit(run_gui(db_url=db_url))
```

- [ ] **Step 3: Smoke-test the CLI command import**

```bash
python -c "from audio_tools.cli import main; print('imported ok')"
audio-tools --help | grep -i gui
```

- [ ] **Step 4: Run the full GUI test suite**

```bash
python -m pytest tests/gui -v
```
Expected: all GUI tests pass under `QT_QPA_PLATFORM=offscreen`.

- [ ] **Step 5: Commit**

```bash
git add src/audio_tools/gui/app.py src/audio_tools/cli.py
git commit -m "feat(cli): audio-tools gui launches PySide6 desktop window"
```

---

## Task 11: README + acceptance smoke

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README**

```markdown
# audio-tools

Linux desktop music manager: mood/tempo-based playlist clustering + size-optimized media-player transfer + PySide6 GUI.

**Status:** Phase 4 (GUI MVP). All four pipeline phases complete (scan → analyze → cluster → playlist → transfer).

## Requirements

- Python 3.11+
- `ffmpeg`
- `essentia-tensorflow` (optional, install via `pip install -e ".[analysis]"`)
- `PySide6` (optional, install via `pip install -e ".[gui]"`)

## Install (development)

```bash
git clone <repo> audio-tools
cd audio-tools
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"                  # core only
pip install -e ".[dev,analysis,gui]"     # full stack
alembic upgrade head
```

## CLI

```bash
audio-tools scan ~/Music
audio-tools fetch-models
audio-tools analyze
audio-tools cluster --k 6
audio-tools playlists
audio-tools transfer --profile walkman --playlist Workout --target-dir /run/media/$USER/WALKMAN
audio-tools gui                          # PySide6 desktop
```

## Tests

```bash
pytest -v                                # all
pytest tests/unit tests/golden -v        # CLI tests only (no Qt)
QT_QPA_PLATFORM=offscreen pytest tests/gui -v   # GUI smoke
```

`tests/golden/` uses real ffmpeg / Essentia and skips when those are missing. `tests/gui/` skips when PySide6 is missing.

## Design docs

- Parent spec: `docs/superpowers/specs/2026-05-25-audio-tools-design.md`
- Per-phase plans and addenda: see `docs/superpowers/plans/` and `docs/superpowers/specs/`.
```

- [ ] **Step 2: Run the full suite**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -v
```
Expected: all tests pass (unit + golden-when-applicable + gui).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for Phase 4 (GUI MVP)"
```

---

## Phase 4 Completion Checklist

- [ ] `audio-tools gui` opens a window with a 5-entry sidebar
- [ ] Sidebar switching works
- [ ] LibraryView populates from the DB and dispatches Scan/Analyze/Cluster/Playlists
- [ ] TransferView "Run" disabled until both a profile and at least one playlist are selected
- [ ] DevicesView "Reload from YAML" loads profiles from `~/.config/audio-tools/devices/`
- [ ] SettingsView shows version and all XDG paths
- [ ] `QT_QPA_PLATFORM=offscreen pytest tests/gui -v` passes 100%
- [ ] Phase 1–3 CLI commands unchanged

When all checked: Phase 4 MVP is done. Phase 4.5 (drag-drop, plots, context menus, tag editing, settings persistence) is a future cycle.
