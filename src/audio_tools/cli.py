import hashlib
import os
from pathlib import Path
from typing import Optional

import click
from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools import __version__, paths
from audio_tools import paths as paths_mod
from audio_tools.core import analyzer as analyzer_mod
from audio_tools.core import clusterer as clusterer_mod
from audio_tools.core import playlist_builder as playlist_mod
from audio_tools.core import scanner
from audio_tools.core.db import make_engine
from audio_tools.core.model_registry import EXPECTED_MODELS, ModelFile  # noqa: F401
from audio_tools.core.models import Cluster as ClusterModel


def _resolve_db_path() -> Path:
    """Honor AUDIO_TOOLS_DB_URL (sqlite-only) or fall back to XDG default."""
    url = os.getenv("AUDIO_TOOLS_DB_URL")
    if url:
        if not url.startswith("sqlite:///"):
            raise click.UsageError(f"Unsupported DB URL (sqlite only): {url}")
        return Path(url.removeprefix("sqlite:///"))
    return paths.db_path()


@click.group()
@click.version_option(__version__, prog_name="audio-tools")
def main():
    """audio-tools: mood/tempo-based music management for Linux."""


@main.command()
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
def scan(directory: Path):
    """Walk DIRECTORY and reconcile tracks with the database."""
    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    with Session(engine, future=True) as session:
        result = scanner.scan(directory, session)
    click.echo(
        f"Scan complete: "
        f"added={result.added} updated={result.updated} "
        f"moved={result.moved} removed={result.removed} skipped={result.skipped}"
    )


def _download_to_file(url: str, dest: Path) -> str:
    """Stream URL → dest atomically; return hex sha256 of the downloaded bytes.

    Tests monkeypatch this function — keep the signature stable.
    """
    import requests

    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    h.update(chunk)
    tmp.replace(dest)
    return h.hexdigest()


@main.command("fetch-models")
def fetch_models():
    """Download Essentia TF models into the user cache (~/.cache/audio-tools/models)."""
    target_dir = paths_mod.models_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    for m in EXPECTED_MODELS:
        dest = target_dir / m.filename
        if dest.exists():
            click.echo(f"  {m.filename}: already present, skipping")
            continue
        click.echo(f"  {m.filename}: downloading…")
        actual = _download_to_file(m.url, dest)
        if m.sha256 != "REPLACE_AT_FETCH_TIME" and actual != m.sha256:
            dest.unlink()
            raise click.ClickException(
                f"sha256 mismatch for {m.filename}: expected {m.sha256}, got {actual}"
            )
        if m.sha256 == "REPLACE_AT_FETCH_TIME":
            click.echo(f"    (record this hash in model_registry.py: {actual})")
    click.echo(f"Models ready in {target_dir}")


def _build_backend(name: str) -> analyzer_mod.AnalyzerBackend:
    if name == "fake":
        if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_BACKEND") != "1":
            raise click.UsageError(
                "fake backend disabled by default. Set AUDIO_TOOLS_ALLOW_FAKE_BACKEND=1 to enable."
            )
        return analyzer_mod.FakeBackend()
    if name == "essentia":
        return analyzer_mod.EssentiaBackend(models_dir=paths_mod.models_dir())
    raise click.UsageError(f"Unknown backend: {name!r} (expected fake|essentia)")


@main.command()
@click.option("--backend", type=click.Choice(["fake", "essentia"]), default="essentia",
              show_default=True)
@click.option("--rescan", is_flag=True, help="Re-analyze every track, ignoring existing features.")
@click.option("--workers", type=int, default=None, help="Worker count (default: os.cpu_count()).")
@click.option("--timeout", type=int, default=300, show_default=True, help="Per-track timeout seconds.")
@click.option("--single-threaded", is_flag=True, help="Run in this process (mostly for debugging).")
def analyze(backend: str, rescan: bool, workers: Optional[int], timeout: int, single_threaded: bool):
    """Extract features for tracks that need analysis."""
    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    backend_impl = _build_backend(backend)
    with Session(engine, future=True) as session:
        result = analyzer_mod.analyze_tracks(
            session,
            backend_impl,
            single_threaded=single_threaded,
            workers=workers,
            timeout_s=timeout,
            rescan=rescan,
        )
    click.echo(f"Analyze complete: analyzed={result.analyzed} failed={result.failed}")


@main.command()
@click.option("--k", type=int, default=None, help="Number of clusters (forces a full re-fit). Default 6 if no clusters exist.")
@click.option("--incremental", is_flag=True, help="Force incremental mode (refuse to re-fit).")
@click.option("--force", is_flag=True, help="Skip the confirmation prompt for destructive re-fit.")
def cluster(k: Optional[int], incremental: bool, force: bool):
    """Cluster tracks by feature embedding."""
    if k is not None and incremental:
        raise click.UsageError("--k and --incremental are mutually exclusive")

    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    with Session(engine, future=True) as session:
        existing = session.scalar(select(ClusterModel)) is not None

        if incremental or (k is None and existing):
            try:
                assigned = clusterer_mod.assign_new(session)
            except clusterer_mod.ClusterError as e:
                raise click.ClickException(str(e))
            click.echo(f"Cluster (incremental): assigned={assigned}")
            return

        target_k = k if k is not None else 6
        if existing and not force:
            click.confirm(
                f"This will discard existing clusters and re-fit with k={target_k}. Continue?",
                abort=True,
            )
        try:
            n = clusterer_mod.recluster(session, k=target_k)
        except clusterer_mod.ClusterError as e:
            raise click.ClickException(str(e))
        click.echo(f"Cluster complete: clusters={target_k} tracks={n}")


@main.command()
@click.option("--out-dir", type=click.Path(file_okay=False, path_type=Path), default=None,
              help="Directory to write m3u files (default: XDG playlists dir).")
def playlists(out_dir: Optional[Path]):
    """Write one m3u per cluster to OUT_DIR."""
    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    target_dir = out_dir or paths_mod.playlists_dir()
    with Session(engine, future=True) as session:
        written = playlist_mod.write_playlists(session, target_dir)
    click.echo(f"Wrote {len(written)} playlist(s) to {target_dir}")


from pathlib import PurePath as _PurePath

from audio_tools.core import device_profile as dp_mod
from audio_tools.core import transfer as transfer_mod
from audio_tools.core.models import (
    Cluster as _ClusterModel,
    ClusterAssignment as _ClusterAssignment,
    DeviceProfile as _DeviceProfile,
)
from audio_tools.core.transcoder import FakeFfmpegRunner, RealFfmpegRunner
from audio_tools.core.transfer_planner import plan as _plan
from audio_tools.core.transfer_target import LocalDirectoryTarget


def _build_ffmpeg_runner(name: str):
    if name == "fake":
        if os.getenv("AUDIO_TOOLS_ALLOW_FAKE_FFMPEG") != "1":
            raise click.UsageError(
                "fake ffmpeg disabled. Set AUDIO_TOOLS_ALLOW_FAKE_FFMPEG=1 to enable."
            )
        return FakeFfmpegRunner()
    if name == "real":
        return RealFfmpegRunner()
    raise click.UsageError(f"Unknown ffmpeg backend: {name}")


def _load_profile(session, name: str, profile_dir: Optional[Path]) -> _DeviceProfile:
    existing = session.scalar(select(_DeviceProfile).where(_DeviceProfile.name == name))
    if existing is not None:
        return existing
    pdir = profile_dir or paths_mod.device_profiles_dir()
    yaml_path = pdir / f"{name}.yaml"
    if not yaml_path.exists():
        raise click.UsageError(f"Profile {name!r} not in DB and {yaml_path} does not exist")
    return dp_mod.upsert_profile(yaml_path, session)


def _collect_tracks_for_playlists(session, playlist_names: tuple[str, ...]) -> list:
    from audio_tools.core.models import Track as _Track
    out: list = []
    for name in playlist_names:
        cluster = session.scalar(select(_ClusterModel).where(_ClusterModel.name == name))
        if cluster is None:
            raise click.UsageError(f"No cluster named {name!r}")
        stmt = (
            select(_Track)
            .join(_ClusterAssignment, _ClusterAssignment.track_id == _Track.id)
            .where(_ClusterAssignment.cluster_id == cluster.id)
            .order_by(_ClusterAssignment.distance.asc())
        )
        out.extend(session.scalars(stmt).all())
    return out


@main.command()
@click.option("--profile", "profile_name", required=True)
@click.option("--profile-dir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--playlist", "playlists", multiple=True, required=True)
@click.option("--target-dir", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--workers", type=int, default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--keep-temp", is_flag=True)
@click.option("--yes", is_flag=True, help="Skip the drop-confirmation prompt.")
@click.option("--ffmpeg-backend", type=click.Choice(["real", "fake"]), default="real")
def transfer(
    profile_name: str,
    profile_dir: Optional[Path],
    playlists: tuple[str, ...],
    target_dir: Optional[Path],
    workers: Optional[int],
    dry_run: bool,
    keep_temp: bool,
    yes: bool,
    ffmpeg_backend: str,
):
    """Transcode and transfer one or more clusters to a device."""
    db_path = _resolve_db_path()
    engine = make_engine(db_path)
    with Session(engine, future=True) as session:
        profile = _load_profile(session, profile_name, profile_dir)
        tracks = _collect_tracks_for_playlists(session, playlists)
        if not tracks:
            click.echo("No tracks to transfer.")
            return

        plan_obj = _plan(tracks, profile)
        click.echo(
            f"Plan: bitrate={plan_obj.bitrate_kbps} kept={len(plan_obj.kept)} "
            f"dropped={len(plan_obj.dropped)} bytes={plan_obj.total_kept_bytes}"
        )
        if plan_obj.warnings:
            for w in plan_obj.warnings:
                click.echo(f"  warning: {w}")
        if plan_obj.dropped and not yes and not dry_run:
            for d in plan_obj.dropped[:10]:
                click.echo(f"  drop: track_id={d.track_id} {d.source_path}")
            if len(plan_obj.dropped) > 10:
                click.echo(f"  …and {len(plan_obj.dropped) - 10} more")
            click.confirm("Proceed with dropping these tracks?", abort=True)

        if dry_run:
            return

        target_root = target_dir or (Path(profile.mount_hint) if profile.mount_hint else None)
        if target_root is None:
            raise click.UsageError("--target-dir required (profile has no mount_hint)")
        target_root.mkdir(parents=True, exist_ok=True)
        target = LocalDirectoryTarget(target_root)
        runner = _build_ffmpeg_runner(ffmpeg_backend)

        playlist_name = playlists[0] if len(playlists) == 1 else "combined"
        m3u_relpath = _PurePath("Playlists") / f"{playlist_name}.m3u"
        outcome = transfer_mod.execute_transfer(
            session=session,
            profile=profile,
            plan=plan_obj,
            target=target,
            ffmpeg=runner,
            m3u_relpath=m3u_relpath,
            cache_dir=paths_mod.cache_dir() / "transcode",
            workers=workers or 1,
            keep_temp=keep_temp,
        )
    click.echo(
        f"Transfer done: copied={outcome.copied} skipped={outcome.skipped} "
        f"failed={outcome.failed}"
    )
