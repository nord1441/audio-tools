import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
except ImportError:
    pytest.skip("PySide6 not installed — skipping GUI tests", allow_module_level=True)


@pytest.fixture
def session_factory_from(tmp_path):
    """Build an in-memory session factory pointed at a tmp DB."""
    from audio_tools.core.db import Base, make_engine, make_session_factory
    engine = make_engine(tmp_path / "gui_test.db")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine), engine
