"""Settings: read-only display of version + XDG paths."""
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SettingsView(QWidget):
    def __init__(self):
        super().__init__()
        from audio_tools import __version__, paths as paths_mod

        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Version:", QLabel(__version__))
        form.addRow("Config dir:", QLabel(str(paths_mod.config_dir())))
        form.addRow("Data dir:", QLabel(str(paths_mod.data_dir())))
        form.addRow("Cache dir:", QLabel(str(paths_mod.cache_dir())))
        form.addRow("Models dir:", QLabel(str(paths_mod.models_dir())))
        form.addRow("Playlists dir:", QLabel(str(paths_mod.playlists_dir())))
        form.addRow("DB path:", QLabel(str(paths_mod.db_path())))
        outer.addLayout(form)

        open_btn = QPushButton("Open data directory")
        open_btn.clicked.connect(self._open_data_dir)
        outer.addWidget(open_btn)
        outer.addStretch()

    def _open_data_dir(self):
        import subprocess
        from audio_tools import paths as paths_mod
        try:
            subprocess.Popen(["xdg-open", str(paths_mod.data_dir())])
        except Exception:
            pass
