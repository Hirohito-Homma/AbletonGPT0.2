"""Tests for warp-vs-onset alignment reporting (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.warp import build_warp_alignment


def test_perfect_alignment():
    times = [0.0, 0.5, 1.0, 1.5]
    report = build_warp_alignment(times, list(times))

    assert report["read_only"] is True
    assert report["warp_marker_count"] == 4
    assert report["onset_count"] == 4
    assert report["markers_on_transient"] == 4
    assert report["onsets_marked"] == 4
    assert report["marker_alignment_ratio"] == 1.0
    assert report["onset_coverage_ratio"] == 1.0
    assert report["marker_to_onset_offset"]["max"] == 0.0


def test_small_offsets_within_tolerance():
    warps = [0.0, 0.5, 1.0]
    onsets = [0.01, 0.52, 1.03]  # all within 0.05 s
    report = build_warp_alignment(warps, onsets, tolerance_seconds=0.05)

    assert report["markers_on_transient"] == 3
    assert report["onsets_marked"] == 3
    assert report["marker_to_onset_offset"]["max"] <= 0.05


def test_offsets_beyond_tolerance_not_counted():
    warps = [0.0, 0.5]
    onsets = [0.2, 0.9]  # ~0.2/0.4 s away
    report = build_warp_alignment(warps, onsets, tolerance_seconds=0.05)

    assert report["markers_on_transient"] == 0
    assert report["onsets_marked"] == 0
    assert report["marker_alignment_ratio"] == 0.0


def test_extra_onsets_lower_coverage_not_alignment():
    warps = [0.0, 1.0]
    onsets = [0.0, 0.5, 1.0]  # 0.5 s onset has no marker
    report = build_warp_alignment(warps, onsets, tolerance_seconds=0.02)

    assert report["markers_on_transient"] == 2  # both markers sit on an onset
    assert report["marker_alignment_ratio"] == 1.0
    assert report["onsets_marked"] == 2  # the middle onset is uncovered
    assert report["onset_coverage_ratio"] == pytest.approx(2 / 3, abs=1e-4)


def test_empty_inputs():
    no_markers = build_warp_alignment([], [0.0, 1.0])
    assert no_markers["marker_alignment_ratio"] is None
    assert no_markers["onset_coverage_ratio"] == 0.0
    assert no_markers["marker_to_onset_offset"]["count"] == 0

    no_onsets = build_warp_alignment([0.0, 1.0], [])
    assert no_onsets["onset_coverage_ratio"] is None
    assert no_onsets["markers_on_transient"] == 0


def test_unsorted_inputs_handled():
    report = build_warp_alignment([1.0, 0.0, 0.5], [0.5, 1.0, 0.0])
    assert report["markers_on_transient"] == 3


def test_rejects_bad_tolerance():
    with pytest.raises(ValueError):
        build_warp_alignment([0.0], [0.0], tolerance_seconds=0.0)
