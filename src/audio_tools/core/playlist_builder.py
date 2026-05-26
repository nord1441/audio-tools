import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from audio_tools.core.models import Cluster, ClusterAssignment, Track

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    """Sanitize a cluster name into a safe filename stem (no extension).

    Replaces runs of disallowed characters with a single underscore and trims
    leading/trailing underscores. Returns empty string when sanitization wipes
    the whole input.
    """
    stripped = _SANITIZE_RE.sub("_", name).strip("_")
    return stripped


def _build_body(rows: list[tuple[Track, ClusterAssignment]]) -> str:
    """Render rows (sorted nearest-to-centroid first) as EXTM3U text."""
    out = ["#EXTM3U"]
    for track, _assignment in rows:
        duration = int(track.duration_s) if track.duration_s is not None else -1
        artist = track.artist or ""
        title = track.title or Path(track.path).stem
        out.append(f"#EXTINF:{duration},{artist} - {title}")
        out.append(track.path)
    out.append("")  # trailing newline
    return "\n".join(out)


def write_playlists(session: Session, out_dir: Path) -> list[Path]:
    """Write one m3u per non-empty cluster into out_dir; return written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for cluster in session.scalars(select(Cluster)).all():
        stmt = (
            select(Track, ClusterAssignment)
            .join(ClusterAssignment, ClusterAssignment.track_id == Track.id)
            .where(ClusterAssignment.cluster_id == cluster.id)
            .order_by(ClusterAssignment.distance.asc())
        )
        rows = session.execute(stmt).all()
        if not rows:
            continue
        stem = _sanitize_filename(cluster.name) or f"cluster_{cluster.id}"
        path = out_dir / f"{stem}.m3u"
        path.write_text(_build_body([(t, a) for (t, a) in rows]), encoding="utf-8")
        written.append(path)
    return written
