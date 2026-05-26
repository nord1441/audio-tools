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
