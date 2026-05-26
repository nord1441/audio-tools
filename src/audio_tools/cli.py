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
