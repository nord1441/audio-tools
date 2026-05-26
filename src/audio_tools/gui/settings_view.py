from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SettingsView(QWidget):
    def __init__(self):
        super().__init__()
        QVBoxLayout(self).addWidget(QLabel("Settings (skeleton)"))
