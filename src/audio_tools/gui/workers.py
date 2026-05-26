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
