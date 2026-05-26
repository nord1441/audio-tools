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


def test_transfer_view_run_button_disabled_without_selection(qtbot, session_factory_from):
    from audio_tools.gui.transfer_view import TransferView
    from PySide6.QtWidgets import QPushButton

    factory, _engine = session_factory_from
    sb = QStatusBar()
    v = TransferView(session_factory=factory, status_bar=sb)
    qtbot.addWidget(v)
    run_btn = v.findChild(QPushButton, "run_btn")
    assert run_btn is not None
    assert not run_btn.isEnabled()


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
