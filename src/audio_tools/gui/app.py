"""GUI entry point. Builds engine + session factory + main window + runs app.exec()."""
import sys
from pathlib import Path
from typing import Optional


def run_gui(db_url: Optional[str] = None) -> int:
    from PySide6.QtWidgets import QApplication

    from audio_tools import paths as paths_mod
    from audio_tools.core.db import make_engine, make_session_factory
    from audio_tools.gui.main_window import MainWindow

    if db_url:
        if not db_url.startswith("sqlite:///"):
            raise SystemExit(f"Unsupported DB URL: {db_url}")
        db_path = Path(db_url.removeprefix("sqlite:///"))
    else:
        db_path = paths_mod.db_path()

    paths_mod.ensure_dirs()
    engine = make_engine(db_path)
    session_factory = make_session_factory(engine)

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(session_factory=session_factory)
    window.show()
    return app.exec()
