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
                features = session.get(Features, track.id)
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
