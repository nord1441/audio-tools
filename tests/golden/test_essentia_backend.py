import importlib.util
from pathlib import Path

import pytest

from audio_tools.core.model_registry import EXPECTED_MODELS

essentia_available = importlib.util.find_spec("essentia") is not None
pytestmark = pytest.mark.skipif(not essentia_available, reason="essentia not installed")

FIXTURE = Path(__file__).parent.parent / "fixtures" / "audio" / "test_tagged.mp3"


def _models_present(models_dir: Path) -> bool:
    return all((models_dir / m.filename).exists() for m in EXPECTED_MODELS)


@pytest.fixture(scope="session")
def models_dir():
    from audio_tools import paths
    md = paths.models_dir()
    if not _models_present(md):
        pytest.skip(f"essentia models not present in {md}; run `audio-tools fetch-models`")
    return md


def test_essentia_backend_extracts_plausible_features(models_dir):
    from audio_tools.core.analyzer import EssentiaBackend

    backend = EssentiaBackend(models_dir=models_dir)
    meta = backend.analyze(FIXTURE)

    # The fixture is a 440Hz sine for 2s — these bounds are very loose by design.
    assert isinstance(meta["embedding"], bytes)
    assert len(meta["embedding"]) == 200 * 4
    assert meta["key"] in {
        "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
        "Db", "Eb", "Gb", "Ab", "Bb",
    }
    assert meta["scale"] in {"major", "minor"}
    if meta["bpm"] is not None:
        assert 0 < meta["bpm"] < 300
