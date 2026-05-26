"""Pinned Essentia TF model files + their canonical URLs and SHA-256s.

URLs come from https://essentia.upf.edu/models/ — pinned at the time of writing.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFile:
    filename: str
    url: str
    sha256: str  # hex digest


EXPECTED_MODELS: tuple[ModelFile, ...] = (
    ModelFile(
        filename="msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/feature-extractors/musicnn/msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_happy-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_happy/mood_happy-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_sad-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_sad/mood_sad-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_aggressive-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_aggressive/mood_aggressive-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
    ModelFile(
        filename="mood_relaxed-msd-musicnn-1.pb",
        url="https://essentia.upf.edu/models/classification-heads/mood_relaxed/mood_relaxed-msd-musicnn-1.pb",
        sha256="REPLACE_AT_FETCH_TIME",
    ),
)
