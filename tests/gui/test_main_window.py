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
