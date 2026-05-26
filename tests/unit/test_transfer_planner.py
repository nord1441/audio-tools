from dataclasses import dataclass
from pathlib import Path

import pytest

from audio_tools.core.transfer_planner import (
    PlannedTrack,
    TransferPlan,
    TransferPlanError,
    plan,
)


@dataclass
class FakeTrack:
    id: int
    path: str
    size: int
    duration_s: float | None


@dataclass
class FakeProfile:
    codec: str
    max_bitrate: int
    min_bitrate: int
    bitrate_step: int
    max_size_bytes: int


def _track(track_id: int, duration: float, size: int = 1000) -> FakeTrack:
    return FakeTrack(id=track_id, path=f"/m/{track_id}.mp3", size=size, duration_s=duration)


def _profile(codec="opus", max_b=128, min_b=64, step=32, cap=10_000_000) -> FakeProfile:
    return FakeProfile(
        codec=codec, max_bitrate=max_b, min_bitrate=min_b,
        bitrate_step=step, max_size_bytes=cap,
    )


def test_plan_fits_at_max_bitrate():
    tracks = [_track(i, duration=180.0) for i in range(3)]
    p = _profile(cap=10_000_000)
    out = plan(tracks, p)
    assert out.bitrate_kbps == 128
    assert len(out.kept) == 3 and not out.dropped


def test_plan_drops_to_lower_bitrate():
    tracks = [_track(i, duration=180.0) for i in range(50)]
    p = _profile(cap=100_000_000)
    out = plan(tracks, p)
    assert out.bitrate_kbps < 128 and out.bitrate_kbps >= 64
    assert len(out.kept) == 50 and not out.dropped


def test_plan_drops_tail_when_even_min_overflows():
    tracks = [_track(i, duration=180.0) for i in range(50)]
    p = _profile(cap=40_000_000)
    out = plan(tracks, p)
    assert out.bitrate_kbps == 64
    assert len(out.kept) + len(out.dropped) == 50
    assert len(out.dropped) > 0
    dropped_ids = [t.track_id for t in out.dropped]
    assert dropped_ids == sorted(dropped_ids, reverse=False)


def test_plan_copy_codec_uses_source_sizes():
    tracks = [_track(i, duration=180.0, size=2_000_000) for i in range(3)]
    p = _profile(codec="copy", cap=10_000_000)
    out = plan(tracks, p)
    assert out.bitrate_kbps == 0
    assert all(pt.output_size_bytes == 2_000_000 for pt in out.kept)


def test_plan_copy_codec_drops_when_oversize():
    tracks = [_track(i, duration=180.0, size=4_000_000) for i in range(5)]
    p = _profile(codec="copy", cap=10_000_000)
    out = plan(tracks, p)
    assert len(out.kept) <= 2
    assert len(out.dropped) >= 3


def test_plan_track_with_none_duration_falls_back_to_size():
    tracks = [
        _track(1, duration=180.0, size=1_000_000),
        FakeTrack(id=2, path="/m/2.mp3", size=2_000_000, duration_s=None),
    ]
    p = _profile(cap=50_000_000)
    out = plan(tracks, p)
    ids = {pt.track_id for pt in out.kept}
    assert ids == {1, 2}


def test_plan_empty_input():
    out = plan([], _profile())
    assert out.kept == [] and out.dropped == []


def test_plan_invalid_profile_min_gt_max():
    p = _profile(max_b=64, min_b=128)
    with pytest.raises(TransferPlanError, match="min_bitrate"):
        plan([_track(1, 180.0)], p)


def test_plan_invalid_profile_zero_step():
    p = _profile(step=0)
    with pytest.raises(TransferPlanError, match="bitrate_step"):
        plan([_track(1, 180.0)], p)


def test_plan_returns_total_bytes_for_kept():
    tracks = [_track(i, duration=180.0, size=2_000_000) for i in range(3)]
    out = plan(tracks, _profile(codec="copy", cap=10_000_000))
    assert out.total_kept_bytes == sum(t.size for t in tracks)
