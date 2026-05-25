import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from audio_tools.core.db import Base
from audio_tools.core import models  # noqa: F401  -- ensure models register


@pytest.fixture
def session(tmp_path):
    """In-memory SQLite session for unit tests."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, future=True) as s:
        yield s
