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
