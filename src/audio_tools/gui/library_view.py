from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LibraryView(QWidget):
    def __init__(self, *, session_factory, status_bar):
        super().__init__()
        QVBoxLayout(self).addWidget(QLabel("Library (skeleton)"))
