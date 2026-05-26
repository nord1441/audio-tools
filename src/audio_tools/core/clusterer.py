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
    """Stub - implemented in Task 11."""
    raise NotImplementedError("assign_new arrives in Task 11")
