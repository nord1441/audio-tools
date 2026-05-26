"""Qt workers wrapping Phase 1–3 core functions for background dispatch."""
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal
from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]


class WorkerSignals(QObject):
    progress = Signal(str)
    error = Signal(str)
    finished = Signal(object)


class BaseWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.setAutoDelete(True)


class ScanWorker(BaseWorker):
    def __init__(self, *, session_factory: SessionFactory, root: Path):
        super().__init__()
        self._session_factory = session_factory
        self._root = Path(root)

    def run(self) -> None:
        from audio_tools.core import scanner
        if not self._root.is_dir():
            self.signals.error.emit(f"Directory not found: {self._root}")
            return
        try:
            with self._session_factory() as session:
                result = scanner.scan(self._root, session)
            self.signals.progress.emit(
                f"Scan: added={result.added} updated={result.updated} "
                f"moved={result.moved} removed={result.removed}"
            )
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))


from typing import Optional, Sequence


class AnalyzeWorker(BaseWorker):
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        backend_name: str,
        workers_count: int | None = None,
        timeout_s: int = 300,
        rescan: bool = False,
    ):
        super().__init__()
        self._session_factory = session_factory
        self._backend_name = backend_name
        self._workers_count = workers_count
        self._timeout_s = timeout_s
        self._rescan = rescan

    def run(self) -> None:
        from audio_tools.core import analyzer as analyzer_mod
        from audio_tools import paths as paths_mod
        import os

        try:
            if self._backend_name == "fake":
                if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND") != "1":
                    self.signals.error.emit(
                        "Fake backend disabled; set AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1"
                    )
                    return
                backend = analyzer_mod.FakeBackend()
            elif self._backend_name == "essentia":
                backend = analyzer_mod.EssentiaBackend(models_dir=paths_mod.models_dir())
            else:
                self.signals.error.emit(f"Unknown backend: {self._backend_name}")
                return

            with self._session_factory() as session:
                result = analyzer_mod.analyze_tracks(
                    session, backend,
                    single_threaded=True,
                    workers=self._workers_count,
                    timeout_s=self._timeout_s,
                    rescan=self._rescan,
                )
            self.signals.progress.emit(
                f"Analyze: analyzed={result.analyzed} failed={result.failed}"
            )
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))


class ClusterWorker(BaseWorker):
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        k: int | None,
        force: bool,
        incremental: bool,
    ):
        super().__init__()
        self._session_factory = session_factory
        self._k = k
        self._force = force
        self._incremental = incremental

    def run(self) -> None:
        from audio_tools.core import clusterer as clusterer_mod
        from audio_tools.core.models import Cluster
        from sqlalchemy import select
        try:
            with self._session_factory() as session:
                existing = session.scalar(select(Cluster)) is not None
                if self._incremental or (self._k is None and existing):
                    assigned = clusterer_mod.assign_new(session)
                    summary = {"mode": "incremental", "assigned": assigned}
                else:
                    k = self._k if self._k is not None else 6
                    assigned = clusterer_mod.recluster(session, k=k)
                    summary = {"mode": "refit", "k": k, "assigned": assigned}
            self.signals.progress.emit(f"Cluster: {summary}")
            self.signals.finished.emit(summary)
        except Exception as e:
            self.signals.error.emit(str(e))


class PlaylistsWorker(BaseWorker):
    def __init__(self, *, session_factory: SessionFactory, out_dir: Path):
        super().__init__()
        self._session_factory = session_factory
        self._out_dir = Path(out_dir)

    def run(self) -> None:
        from audio_tools.core import playlist_builder as pl_mod
        try:
            with self._session_factory() as session:
                written = pl_mod.write_playlists(session, self._out_dir)
            self.signals.progress.emit(f"Playlists: wrote {len(written)} files")
            self.signals.finished.emit(written)
        except Exception as e:
            self.signals.error.emit(str(e))


class TransferWorker(BaseWorker):
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        profile_name: str,
        playlists: Sequence[str],
        target_dir: Path,
        ffmpeg_backend: str,
        workers_count: int,
    ):
        super().__init__()
        self._session_factory = session_factory
        self._profile_name = profile_name
        self._playlists = list(playlists)
        self._target_dir = Path(target_dir)
        self._ffmpeg_backend = ffmpeg_backend
        self._workers_count = workers_count

    def run(self) -> None:
        import os
        from pathlib import PurePath
        from sqlalchemy import select

        from audio_tools.core import transfer as transfer_mod
        from audio_tools.core.models import (
            Cluster,
            ClusterAssignment,
            DeviceProfile,
            Track,
        )
        from audio_tools.core.transcoder import FakeFfmpegRunner, RealFfmpegRunner
        from audio_tools.core.transfer_planner import plan as plan_fn
        from audio_tools.core.transfer_target import LocalDirectoryTarget
        from audio_tools import paths as paths_mod

        try:
            if self._ffmpeg_backend == "fake":
                if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_FFMPEG") != "1":
                    self.signals.error.emit("Fake ffmpeg disabled; set AUDIO_TOOLS_ALLOW_FAKE_FFMPEG=1")
                    return
                runner = FakeFfmpegRunner()
            else:
                runner = RealFfmpegRunner()

            with self._session_factory() as session:
                profile = session.scalar(select(DeviceProfile).where(DeviceProfile.name == self._profile_name))
                if profile is None:
                    self.signals.error.emit(f"Profile {self._profile_name!r} not in DB")
                    return

                tracks: list[Track] = []
                for plist in self._playlists:
                    c = session.scalar(select(Cluster).where(Cluster.name == plist))
                    if c is None:
                        self.signals.error.emit(f"No cluster named {plist!r}")
                        return
                    stmt = (
                        select(Track)
                        .join(ClusterAssignment, ClusterAssignment.track_id == Track.id)
                        .where(ClusterAssignment.cluster_id == c.id)
                        .order_by(ClusterAssignment.distance.asc())
                    )
                    tracks.extend(session.scalars(stmt).all())

                plan_obj = plan_fn(tracks, profile)
                outcome = transfer_mod.execute_transfer(
                    session=session,
                    profile=profile,
                    plan=plan_obj,
                    target=LocalDirectoryTarget(self._target_dir),
                    ffmpeg=runner,
                    m3u_relpath=PurePath("Playlists") / f"{self._playlists[0]}.m3u",
                    cache_dir=paths_mod.cache_dir() / "transcode",
                    workers=self._workers_count,
                )
            self.signals.progress.emit(
                f"Transfer: copied={outcome.copied} skipped={outcome.skipped} failed={outcome.failed}"
            )
            self.signals.finished.emit(outcome)
        except Exception as e:
            self.signals.error.emit(str(e))
