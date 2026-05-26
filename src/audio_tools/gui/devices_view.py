from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class DevicesView(QWidget):
    def __init__(self, *, session_factory, status_bar):
        super().__init__()
        QVBoxLayout(self).addWidget(QLabel("Devices (skeleton)"))
