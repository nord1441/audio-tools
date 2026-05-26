from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from audio_tools.core.db import Base


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    mtime: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha1: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    artist: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    album: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bitrate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    last_analysis_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_tracks_sha1", "sha1"),)


class DeviceProfile(Base):
    __tablename__ = "device_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    mount_hint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    codec: Mapped[str] = mapped_column(String, nullable=False)
    container: Mapped[str] = mapped_column(String, nullable=False)
    max_bitrate: Mapped[int] = mapped_column(Integer, nullable=False)
    min_bitrate: Mapped[int] = mapped_column(Integer, nullable=False)
    bitrate_step: Mapped[int] = mapped_column(Integer, nullable=False)
    max_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_rate_max: Mapped[int] = mapped_column(Integer, nullable=False)
    m3u_path_style: Mapped[str] = mapped_column(String, nullable=False)
    folder_layout: Mapped[str] = mapped_column(String, nullable=False)


class Features(Base):
    __tablename__ = "features"

    track_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    bpm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    scale: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    energy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    danceability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_happy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_sad: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_aggressive: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mood_relaxed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    loudness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spectral_centroid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    k_value: Mapped[int] = mapped_column(Integer, nullable=False)
    centroid: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ClusterAssignment(Base):
    __tablename__ = "cluster_assignments"

    track_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False
    )
    distance: Mapped[float] = mapped_column(Float, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_cluster_assignments_cluster_id", "cluster_id"),)


class TransferSession(Base):
    __tablename__ = "transfer_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("device_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    bytes_transferred: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bitrate_kbps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kept_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dropped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
