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
