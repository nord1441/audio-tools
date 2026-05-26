from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import select

from audio_tools.core.clusterer import ClusterError, assign_new, recluster
from audio_tools.core.models import Cluster, ClusterAssignment, Features, Track


def _seed_tracks_with_blob_embeddings(session, n_per_cluster: int = 5, k: int = 3):
    """Create n_per_cluster * k tracks whose embeddings are clearly separated."""
    rng = np.random.default_rng(0)
    for cluster_i in range(k):
        center = np.zeros(200, dtype=np.float32)
        center[cluster_i * 10:(cluster_i + 1) * 10] = 10.0  # disjoint signal
        for j in range(n_per_cluster):
            t = Track(path=f"/m/c{cluster_i}-t{j}.mp3", mtime=0.0, size=1)
            session.add(t)
            session.flush()
            emb = center + rng.standard_normal(200).astype(np.float32) * 0.1
            session.add(Features(
                track_id=t.id,
                embedding=emb.tobytes(),
                analyzed_at=datetime.utcnow(),
            ))
    session.commit()


def test_recluster_creates_k_clusters_and_assigns_all(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    n = recluster(session, k=3)
    assert n == 15
    clusters = session.scalars(select(Cluster)).all()
    assert len(clusters) == 3
    for c in clusters:
        assert c.k_value == 3
        assert len(c.centroid) == 200 * 4
        assert c.name.startswith("Cluster")
    assignments = session.scalars(select(ClusterAssignment)).all()
    assert len(assignments) == 15
    # Every track is in exactly one cluster
    track_ids = {a.track_id for a in assignments}
    assert len(track_ids) == 15


def test_recluster_groups_well_separated_points(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    # Group track ids by cluster, then verify track paths share their seeded cluster.
    by_cluster: dict[int, list[str]] = {}
    for assignment in session.scalars(select(ClusterAssignment)).all():
        track = session.get(Track, assignment.track_id)
        by_cluster.setdefault(assignment.cluster_id, []).append(track.path)
    for paths in by_cluster.values():
        prefixes = {p.split("/")[-1].split("-")[0] for p in paths}
        assert len(prefixes) == 1, f"cluster mixed seed groups: {prefixes}"


def test_recluster_overwrites_prior_clusters(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    recluster(session, k=2)
    assert len(session.scalars(select(Cluster)).all()) == 2


def test_assign_new_routes_unassigned_to_nearest_cluster(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)

    # Add a new track whose embedding is dead-on cluster 0's center
    new = Track(path="/m/new.mp3", mtime=0.0, size=1)
    session.add(new); session.flush()
    seeded_center = np.zeros(200, dtype=np.float32)
    seeded_center[0:10] = 10.0
    session.add(Features(track_id=new.id, embedding=seeded_center.tobytes(), analyzed_at=datetime.utcnow()))
    session.commit()

    count = assign_new(session)
    assert count == 1

    a = session.get(ClusterAssignment, new.id)
    assert a is not None
    # The other 5 tracks seeded near center 0 share its cluster id.
    sibling_paths = [
        session.get(Track, x.track_id).path
        for x in session.scalars(select(ClusterAssignment).where(ClusterAssignment.cluster_id == a.cluster_id)).all()
        if x.track_id != new.id
    ]
    assert all("c0-" in p for p in sibling_paths)


def test_assign_new_is_idempotent(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    # No new tracks → 0 new assignments
    assert assign_new(session) == 0


def test_assign_new_without_clusters_raises(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    # Skip recluster; no clusters exist yet
    with pytest.raises(ClusterError, match="no clusters"):
        assign_new(session)


def test_assign_new_does_not_change_existing_assignments(session):
    _seed_tracks_with_blob_embeddings(session, n_per_cluster=5, k=3)
    recluster(session, k=3)
    before = {a.track_id: a.cluster_id for a in session.scalars(select(ClusterAssignment)).all()}

    # Add 3 new tracks belonging clearly to cluster 1
    seeded_center = np.zeros(200, dtype=np.float32)
    seeded_center[10:20] = 10.0
    for j in range(3):
        t = Track(path=f"/m/late-{j}.mp3", mtime=0.0, size=1)
        session.add(t); session.flush()
        session.add(Features(track_id=t.id, embedding=seeded_center.tobytes(), analyzed_at=datetime.utcnow()))
    session.commit()

    assign_new(session)

    after = {a.track_id: a.cluster_id for a in session.scalars(select(ClusterAssignment)).all()}
    for tid, cid in before.items():
        assert after[tid] == cid  # untouched
