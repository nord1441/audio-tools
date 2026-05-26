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
