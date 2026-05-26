import pytest
from sqlalchemy.orm import Session

from audio_tools.core.db import Base, make_engine
from audio_tools.core import models  # noqa: F401  -- ensure models register


@pytest.fixture
def session(tmp_path):
    """File-backed SQLite session for unit tests (per-test fresh DB)."""
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        yield s
