"""Tests for mix-vs-reference comparison (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.reference import build_reference_comparison


def _profile(lufs=-14.0, lra=6.0, tp=-1.0, crest=12.0, centroid=2000.0, rolloff=6000.0):
    return {
        "integrated_lufs": lufs,
        "loudness_range_lu": lra,
        "true_peak_dbtp": tp,
        "crest_factor_db": crest,
        "centroid_hz": centroid,
        "rolloff_hz": rolloff,
    }


def test_matched_profiles_report_no_gaps():
    report = build_reference_comparison(_profile(), _profile())

    assert report["read_only"] is True
    assert report["deltas"]["loudness_lu"] == 0.0
    assert report["guidance"] == ["Mix and reference are closely matched on the measured metrics."]


def test_quieter_mix_guidance():
    report = build_reference_comparison(_profile(lufs=-16.0), _profile(lufs=-12.0))

    assert report["deltas"]["loudness_lu"] == -4.0
    assert any("4.0 LU quieter" in note for note in report["guidance"])


def test_brighter_mix_flagged_relative_to_reference_centroid():
    report = build_reference_comparison(_profile(centroid=3000.0), _profile(centroid=2000.0))

    # 1000 Hz delta > 10% of the 2000 Hz reference centroid.
    assert report["deltas"]["brightness_hz"] == 1000.0
    assert any("brighter" in note for note in report["guidance"])


def test_small_brightness_difference_not_flagged():
    report = build_reference_comparison(_profile(centroid=2050.0), _profile(centroid=2000.0))

    assert not any("brighter" in note or "darker" in note for note in report["guidance"])


def test_dynamics_and_crest_guidance():
    report = build_reference_comparison(
        _profile(lra=4.0, crest=9.0), _profile(lra=8.0, crest=13.0)
    )

    assert any("narrower" in note or "less dynamics" in note for note in report["guidance"])
    assert any("more compressed" in note for note in report["guidance"])


def test_none_metrics_are_skipped():
    mix = _profile()
    mix["integrated_lufs"] = None
    report = build_reference_comparison(mix, _profile())

    assert report["deltas"]["loudness_lu"] is None
    assert not any("LU louder" in note or "LU quieter" in note for note in report["guidance"])


def _bands(low=0.2, low_mid=0.2, mid=0.2, high_mid=0.2, high=0.2):
    return {"low": low, "low_mid": low_mid, "mid": mid, "high_mid": high_mid, "high": high}


def test_band_deltas_and_guidance():
    mix = _profile()
    mix["bands"] = _bands(low=0.30, high=0.10)  # more low, less high
    ref = _profile()
    ref["bands"] = _bands(low=0.20, high=0.20)

    report = build_reference_comparison(mix, ref)

    assert report["deltas"]["bands"]["low"] == 0.1
    assert report["deltas"]["bands"]["high"] == -0.1
    assert any("more low energy" in note for note in report["guidance"])
    assert any("less high energy" in note for note in report["guidance"])


def test_small_band_differences_not_flagged():
    mix = _profile()
    mix["bands"] = _bands(low=0.21)  # only +1 point
    ref = _profile()
    ref["bands"] = _bands()

    report = build_reference_comparison(mix, ref)

    assert not any("energy than the reference" in note for note in report["guidance"])


def test_bands_absent_leaves_no_band_delta():
    report = build_reference_comparison(_profile(), _profile())
    assert "bands" not in report["deltas"]
