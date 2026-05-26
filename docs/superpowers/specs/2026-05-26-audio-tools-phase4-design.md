# audio-tools Phase 4 (PySide6 GUI — MVP) Design Addendum

**Date**: 2026-05-26
**Status**: Approved
**Parent spec**: [`2026-05-25-audio-tools-design.md`](./2026-05-25-audio-tools-design.md)

Phase 4 implements §9 (GUI) of the parent spec as an **MVP shell**: all five views from §9 are present as skeletons that can be opened from the sidebar, and a worker layer dispatches background work to Phase 1–3 core modules. Rich UX (drag-drop between clusters, pie-chart transfer preview, elbow-method plot, tag editor, right-click context menus, settings persistence) is explicitly deferred to a Phase 4.5 follow-up.

## Goals

- Provide a working desktop binary (`audio-tools gui`) that opens, navigates, and runs scan / analyze / cluster / playlists / transfer against the same DB the CLI uses.
- Establish the worker pattern so Phase 4.5 widgets plug in without re-plumbing.
- Verify with pytest-qt smoke tests that run headless on CI via the `offscreen` Qt platform.

## Out of scope (Phase 4.5)

- Drag-and-drop between clusters.
- Custom track ordering inside a cluster.
- Pie-chart / circular bar / elbow plot.
- Right-click context menu (`Transfer now`, `Move to cluster…`, `Reanalyze`, `Open in file manager`).
- DeviceProfile YAML edit form (file editor button only).
- Settings persistence (config.yaml round-trip).
- `QAbstractItemModel` swap for virtual scrolling over 10 k+ tracks (MVP uses `QStandardItemModel`).
- Track tag editing.

## Module Layout

```
src/audio_tools/
  cli.py                       # +gui subcommand (lazy PySide6 import)
  gui/
    __init__.py
    app.py                     # QApplication + main entry
    main_window.py             # QMainWindow + sidebar + QStackedWidget
    library_view.py
    cluster_view.py
    transfer_view.py
    devices_view.py
    settings_view.py
    workers.py                 # QRunnable wrappers + Signals
    db_session.py              # GUI-scoped Session lifecycle helper
tests/
  gui/
    __init__.py
    conftest.py                # pytest-qt qtbot configuration + offscreen
    test_main_window.py
    test_workers.py
    test_views_smoke.py
```

**Responsibility boundaries:**
- `app.py` — bootstrap only. Builds `QApplication`, the engine + session factory (shared across views via dependency injection), the main window, and `app.exec()`.
- `main_window.py` — sidebar, stacked widget, status bar wiring. Knows about each view by name only.
- Each `*_view.py` — one view class. Constructs its widgets and connects to the worker layer. Receives a `Session` callable from the main window.
- `workers.py` — `QRunnable` subclasses that wrap Phase 1–3 functions and emit progress/error/finished signals. Workers never touch UI widgets directly.

## Dependencies

`pyproject.toml`:

```toml
[project.optional-dependencies]
gui = [
    "PySide6>=6.6",
    "pytest-qt>=4.4",   # smoke tests live here
]
```

Install for development: `pip install -e ".[dev,gui]"`.

The base CLI tooling does **not** depend on PySide6. `cli.py` imports `gui.app` lazily inside the `gui` command handler.

## Worker Pattern

```python
# gui/workers.py
from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    progress = Signal(str)            # human-readable status line
    error = Signal(str)
    finished = Signal(object)         # result payload (dataclass per worker)


class BaseWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
```

Concrete workers:
- `ScanWorker(session_factory, root: Path)`
- `AnalyzeWorker(session_factory, backend_name: str, workers: int, timeout_s: int, rescan: bool)`
- `ClusterWorker(session_factory, k: int | None, force: bool, incremental: bool)`
- `PlaylistsWorker(session_factory, out_dir: Path)`
- `TransferWorker(session_factory, profile_name: str, playlists: list[str], target_dir: Path, ffmpeg_backend: str, workers: int)`

Each worker opens its own `Session` in `run()` (the GUI thread's session is not thread-safe), reuses Phase 1–3 functions, and emits results. Errors are caught and emitted via `signals.error`.

Workers are dispatched through a single project-wide `QThreadPool` (default sized to `os.cpu_count()`). Cancellation in MVP is cooperative-only: a `CancellationToken` (a `threading.Event`) is passed in and the worker checks it between sub-tasks. Phase 4 wires the token but does not yet expose a cancel button (Phase 4.5).

## Views

### LibraryView

- `QToolBar` with buttons: Scan…, Analyze, Cluster, Write Playlists.
- `QTableView` backed by `QStandardItemModel` with columns:
  | id | title | artist | bpm | key | cluster | analyzed? |
- Loaded by `_reload_table()` which queries the DB and populates rows.
- Scan… opens a `QFileDialog.getExistingDirectory` and dispatches `ScanWorker`. On `finished`, calls `_reload_table()`.
- Analyze dispatches `AnalyzeWorker(backend_name="essentia")`. Reads `AUDIO_TOOLS_ALLOW_FAKE_BACKEND` env to allow fake.
- Cluster opens a tiny modal: spinbox for `k`, "Incremental" checkbox, OK/Cancel. Dispatches `ClusterWorker`.
- Write Playlists dispatches `PlaylistsWorker(out_dir=paths.playlists_dir())`.

### ClusterView

- Left: `QListWidget` of clusters (name, member count).
- Right: `QListWidget` of tracks in the selected cluster, sorted by `distance` ascending.
- No drag-drop, no rename, no recoloring (deferred).

### TransferView

- Form layout:
  - Profile: `QComboBox` populated from DB.
  - Playlists: `QListWidget` (multi-select) populated from clusters.
  - Target dir: `QLineEdit` + browse button.
  - ffmpeg backend: `QComboBox` (real / fake).
  - Workers: `QSpinBox` (default cpu_count).
  - "Dry run" checkbox.
  - "Run" button.
- Below the form: `QPlainTextEdit` (read-only) for progress log.
- "Run" dispatches `TransferWorker`. Progress messages append to the log. `finished` shows a summary line. On `error`, the log line is colored red.

### DevicesView

- `QTableView` of DeviceProfile rows: name, codec, container, max_bitrate, max_size_bytes, mount_hint.
- "Reload from YAML" button: scans `paths.device_profiles_dir()` via the Phase 1 loader (`load_all_profiles`).
- "Open YAML directory" button: launches `xdg-open` on the profile dir.

### SettingsView

- Read-only labels:
  - Version (`audio_tools.__version__`)
  - DB path
  - Config dir
  - Data dir
  - Cache dir
  - Models dir
  - Playlists dir
- "Open data directory" button (xdg-open).

## Session Lifecycle

The GUI is single-process and long-lived. Strategy:

- The main window holds an `Engine` (built from `paths.db_path()` resolved at startup) and a `session_factory` (`make_session_factory`).
- Each view receives `session_factory` (a callable) at construction. Views open a short-lived session for read queries inside their own methods (`with session_factory() as s: …`) — they do not hold a session across user interactions.
- Workers receive `session_factory` and open one fresh session inside `run()` (separate thread).
- After a worker `finished` signal, the view that dispatched it re-queries to refresh.

This avoids cross-thread session sharing and stale-cache issues entirely at the cost of a couple of extra queries per refresh — acceptable for MVP.

## CLI Hook

```
audio-tools gui [--db PATH]
```

Implemented in `cli.py`:

```python
@main.command("gui")
@click.option("--db", "db_url", type=str, default=None)
def gui_cmd(db_url):
    try:
        from audio_tools.gui.app import run_gui
    except ImportError as e:
        raise click.UsageError(
            "GUI dependencies not installed. Run `pip install -e .[gui]` first.\n"
            f"({e})"
        )
    raise SystemExit(run_gui(db_url=db_url))
```

`run_gui(db_url)` resolves to either the passed URL or the default `paths.db_path()`, builds the engine, builds the main window, runs `app.exec()`, returns the exit code.

## Testing

### pytest-qt configuration

`tests/gui/conftest.py`:

```python
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qapp_args():
    return ["audio-tools-test"]
```

Each test function takes the standard `qtbot` fixture and asserts on widget state after exercising user-style interactions.

### Smoke tests

`tests/gui/test_main_window.py`:
- main window opens and exits cleanly.
- sidebar has exactly 5 entries.
- clicking each entry switches the stacked widget to the matching index.
- status bar accepts text.

`tests/gui/test_views_smoke.py`:
- Each view can be constructed with a stubbed `session_factory` returning a real in-memory `Session`.
- LibraryView reload after seeding two tracks shows two rows.
- ClusterView shows zero clusters initially; after seeding, one row.
- TransferView refuses "Run" when no profile/playlist selected (button disabled or warning text shown).
- DevicesView "Reload from YAML" against an empty directory does not crash.
- SettingsView labels are non-empty.

`tests/gui/test_workers.py`:
- `ScanWorker.run()` against a tmp directory with two MP3 fixtures emits `finished` with a `ScanResult`-shaped payload (verified via `qtbot.waitSignal`).
- `AnalyzeWorker` with `FakeBackend` likewise.
- `TransferWorker` with `FakeFfmpegRunner` likewise.

### CI

CI uses `xvfb-run` or `QT_QPA_PLATFORM=offscreen`. The latter is preferred (no Xvfb dep). pytest invokes `tests/gui/` only when `pip install -e ".[gui]"` was run; otherwise the directory is skipped via a collection hook in `tests/gui/conftest.py` (`pytest.skip(... allow_module_level=True)` if PySide6 import fails).

## Acceptance for Phase 4

- `audio-tools gui` launches a window with a sidebar listing 5 entries (Library, Clusters, Transfer, Devices, Settings).
- Clicking each sidebar entry switches the right pane.
- LibraryView's Scan/Analyze/Cluster/Playlists buttons all wire up and produce a status-bar message on completion (in either real or fake mode).
- TransferView's Run button completes a transfer to a tmp directory when fake ffmpeg is enabled.
- `pytest tests/gui/ -v` passes 100% under offscreen Qt.
- The non-GUI test suite (`pytest tests/unit tests/golden -v`) still passes.
- Phase 1–3 CLI commands still work unchanged.

When done: Phase 4 MVP is complete. Phase 4.5 (drag-drop, plots, context menus, tag editing, settings persistence) is a separate planning cycle.
