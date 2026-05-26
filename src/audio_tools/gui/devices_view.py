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
