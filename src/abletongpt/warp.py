"""Compare an audio clip's warp markers against detected onsets.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_warp_alignment`
takes a clip's warp-marker sample times (seconds into the audio) and a list of detected
onset times (also seconds) and reports how well the two agree: whether each warp marker
sits on a real transient, and whether each transient is marked. Read-only and deterministic.
"""

from __future__ import annotations

import bisect
import statistics
from typing import Any


def _nearest_distance(value: float, sorted_values: list[float]) -> float | None:
    """Absolute distance from ``value`` to the closest entry of a sorted list, or ``None``."""
    if not sorted_values:
        return None
    index = bisect.bisect_left(sorted_values, value)
    candidates = []
    if index < len(sorted_values):
        candidates.append(abs(sorted_values[index] - value))
    if index > 0:
        candidates.append(abs(value - sorted_values[index - 1]))
    return min(candidates)


def _offset_stats(offsets: list[float | None]) -> dict[str, Any]:
    present = [offset for offset in offsets if offset is not None]
    if not present:
        return {"count": 0, "mean": None, "median": None, "max": None}
    return {
        "count": len(present),
        "mean": round(statistics.fmean(present), 4),
        "median": round(statistics.median(present), 4),
        "max": round(max(present), 4),
    }


def build_warp_alignment(
    warp_sample_times: list[float],
    onset_times: list[float],
    *,
    tolerance_seconds: float = 0.05,
) -> dict[str, Any]:
    """Report how well warp markers and onsets line up.

    ``warp_sample_times`` and ``onset_times`` are both in seconds into the audio. For each
    warp marker the nearest onset distance says whether it sits on a transient; for each
    onset the nearest marker distance says whether the transient is marked. Counts within
    ``tolerance_seconds`` give an alignment ratio and a coverage ratio.
    """
    if tolerance_seconds <= 0.0:
        raise ValueError("tolerance_seconds must be positive")

    warps = sorted(float(value) for value in warp_sample_times)
    onsets = sorted(float(value) for value in onset_times)

    marker_offsets = [_nearest_distance(warp, onsets) for warp in warps]
    onset_offsets = [_nearest_distance(onset, warps) for onset in onsets]

    markers_on_transient = sum(
        1 for offset in marker_offsets if offset is not None and offset <= tolerance_seconds
    )
    onsets_marked = sum(
        1 for offset in onset_offsets if offset is not None and offset <= tolerance_seconds
    )

    return {
        "read_only": True,
        "tolerance_seconds": tolerance_seconds,
        "warp_marker_count": len(warps),
        "onset_count": len(onsets),
        "markers_on_transient": markers_on_transient,
        "onsets_marked": onsets_marked,
        "marker_alignment_ratio": round(markers_on_transient / len(warps), 4) if warps else None,
        "onset_coverage_ratio": round(onsets_marked / len(onsets), 4) if onsets else None,
        "marker_to_onset_offset": _offset_stats(marker_offsets),
        "onset_to_marker_offset": _offset_stats(onset_offsets),
    }
