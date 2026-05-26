import hashlib
import os
from pathlib import Path

import click
from sqlalchemy.orm import Session

from audio_tools import __version__, paths
from audio_tools import paths as paths_mod
from audio_tools.core import scanner
from audio_tools.core.db import make_engine
from audio_tools.core.model_registry import EXPECTED_MODELS, ModelFile  # noqa: F401


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
