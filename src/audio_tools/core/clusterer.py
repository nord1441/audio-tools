from datetime import datetime
from typing import Sequence

import numpy as np
from sklearn.cluster import KMeans
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from audio_tools.core.models import Cluster, ClusterAssignment, Features


class ClusterError(Exception):
    """Raised when clustering preconditions are not met."""


def _load_embeddings(session: Session) -> tuple[list[int], np.ndarray]:
    rows = session.scalars(select(Features)).all()
    if not rows:
        raise ClusterError("no features rows; run `audio-tools analyze` first")
    track_ids = [r.track_id for r in rows]
    mat = np.stack([
        np.frombuffer(r.embedding, dtype=np.float32) for r in rows
    ])
    return track_ids, mat


def recluster(session: Session, k: int) -> int:
    """Run full KMeans on every feature row; rebuild clusters and assignments.

    Returns the number of tracks assigned.
    """
    if k < 2:
        raise ClusterError(f"k must be >= 2, got {k}")
    track_ids, embeddings = _load_embeddings(session)
    if embeddings.shape[0] < k:
        raise ClusterError(
            f"only {embeddings.shape[0]} feature rows, cannot cluster into k={k}"
        )

    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(embeddings)
    centroids = model.cluster_centers_.astype(np.float32)

    # Wipe and rebuild
    session.execute(delete(ClusterAssignment))
    session.execute(delete(Cluster))
    session.flush()

    now = datetime.utcnow()
    cluster_rows = [
        Cluster(
            name=f"Cluster {i + 1}",
            color=None,
            k_value=k,
            centroid=centroids[i].tobytes(),
            created_at=now,
        )
        for i in range(k)
    ]
    session.add_all(cluster_rows)
    session.flush()  # populate ids

    for tid, label, emb in zip(track_ids, labels, embeddings):
        c = cluster_rows[int(label)]
        distance = float(np.linalg.norm(emb - centroids[label]))
        session.add(ClusterAssignment(
            track_id=tid,
            cluster_id=c.id,
            distance=distance,
            assigned_at=now,
        ))
    session.commit()
    return len(track_ids)


def assign_new(session: Session) -> int:
    """Assign tracks whose features exist but have no cluster_assignments row.

    Uses the nearest existing centroid; never modifies existing assignments.
    Returns the count of new assignments.
    """
    clusters = session.scalars(select(Cluster)).all()
    if not clusters:
        raise ClusterError("no clusters; run `audio-tools cluster --k N` first")

    centroids = np.stack([
        np.frombuffer(c.centroid, dtype=np.float32) for c in clusters
    ])
    cluster_ids = [c.id for c in clusters]

    unassigned_stmt = (
        select(Features)
        .outerjoin(ClusterAssignment, ClusterAssignment.track_id == Features.track_id)
        .where(ClusterAssignment.track_id.is_(None))
    )
    unassigned = session.scalars(unassigned_stmt).all()
    if not unassigned:
        return 0

    now = datetime.utcnow()
    for feat in unassigned:
        emb = np.frombuffer(feat.embedding, dtype=np.float32)
        distances = np.linalg.norm(centroids - emb, axis=1)
        best = int(np.argmin(distances))
        session.add(ClusterAssignment(
            track_id=feat.track_id,
            cluster_id=cluster_ids[best],
            distance=float(distances[best]),
            assigned_at=now,
        ))
    session.commit()
    return len(unassigned)
