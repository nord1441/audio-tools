import os
from pathlib import Path

import click
from sqlalchemy.orm import Session

from audio_tools import __version__, paths
from audio_tools.core import scanner
from audio_tools.core.db import make_engine


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
