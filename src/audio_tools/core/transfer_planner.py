"""Pure-Python bitrate + tail-drop search. No I/O, no DB."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class _TrackLike(Protocol):
    id: int
    path: str
    size: int
    duration_s: float | None


class _ProfileLike(Protocol):
    codec: str
    max_bitrate: int
    min_bitrate: int
    bitrate_step: int
    max_size_bytes: int


@dataclass(frozen=True)
class PlannedTrack:
    track_id: int
    source_path: Path
    output_size_bytes: int
    codec: str
    bitrate_kbps: int


@dataclass
class TransferPlan:
    bitrate_kbps: int
    kept: list[PlannedTrack]
    dropped: list[PlannedTrack]
    total_kept_bytes: int
    warnings: list[str] = field(default_factory=list)


class TransferPlanError(ValueError):
    pass


def _predict(track: _TrackLike, codec: str, bitrate_kbps: int) -> int:
    if codec == "copy":
        return track.size
    if track.duration_s is None:
        return track.size
    bits = track.duration_s * bitrate_kbps * 1000.0
    return int(bits / 8 * 1.05)


def _build_planned(tracks: list[_TrackLike], codec: str, bitrate_kbps: int) -> list[PlannedTrack]:
    return [
        PlannedTrack(
            track_id=t.id,
            source_path=Path(t.path),
            output_size_bytes=_predict(t, codec, bitrate_kbps),
            codec=codec,
            bitrate_kbps=0 if codec == "copy" else bitrate_kbps,
        )
        for t in tracks
    ]


def _drop_from_tail(planned: list[PlannedTrack], cap: int) -> tuple[list[PlannedTrack], list[PlannedTrack]]:
    kept = list(planned)
    dropped: list[PlannedTrack] = []
    total = sum(p.output_size_bytes for p in kept)
    while kept and total > cap:
        d = kept.pop()
        dropped.append(d)
        total -= d.output_size_bytes
    return kept, list(reversed(dropped))


def plan(tracks: list[_TrackLike], profile: _ProfileLike) -> TransferPlan:
    if profile.min_bitrate > profile.max_bitrate:
        raise TransferPlanError(
            f"min_bitrate ({profile.min_bitrate}) > max_bitrate ({profile.max_bitrate})"
        )
    if profile.bitrate_step <= 0:
        raise TransferPlanError(f"bitrate_step must be > 0, got {profile.bitrate_step}")

    if not tracks:
        return TransferPlan(bitrate_kbps=0, kept=[], dropped=[], total_kept_bytes=0)

    warnings: list[str] = []
    if any(t.duration_s is None for t in tracks):
        warnings.append("some tracks have no duration; sizes estimated from source bytes")

    codec = profile.codec
    if codec == "copy":
        planned = _build_planned(tracks, codec="copy", bitrate_kbps=0)
        kept, dropped = _drop_from_tail(planned, profile.max_size_bytes)
        return TransferPlan(
            bitrate_kbps=0,
            kept=kept, dropped=dropped,
            total_kept_bytes=sum(p.output_size_bytes for p in kept),
            warnings=warnings,
        )

    bitrate = profile.max_bitrate
    chosen_planned: list[PlannedTrack] | None = None
    while bitrate >= profile.min_bitrate:
        planned = _build_planned(tracks, codec=codec, bitrate_kbps=bitrate)
        total = sum(p.output_size_bytes for p in planned)
        if total <= profile.max_size_bytes:
            chosen_planned = planned
            break
        bitrate -= profile.bitrate_step

    if chosen_planned is None:
        bitrate = profile.min_bitrate
        planned = _build_planned(tracks, codec=codec, bitrate_kbps=bitrate)
        kept, dropped = _drop_from_tail(planned, profile.max_size_bytes)
        return TransferPlan(
            bitrate_kbps=bitrate,
            kept=kept, dropped=dropped,
            total_kept_bytes=sum(p.output_size_bytes for p in kept),
            warnings=warnings,
        )

    return TransferPlan(
        bitrate_kbps=bitrate,
        kept=chosen_planned,
        dropped=[],
        total_kept_bytes=sum(p.output_size_bytes for p in chosen_planned),
        warnings=warnings,
    )
