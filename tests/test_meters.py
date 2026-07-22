"""Tests for the live master-meter headroom report (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.meters import (
    build_live_headroom_report,
    meter_level_to_dbfs,
    summarize_meter_samples,
)
from abletongpt.targets import get_target


def test_meter_level_to_dbfs_endpoints():
    assert meter_level_to_dbfs(1.0) == 0.0
    assert meter_level_to_dbfs(0.5) == pytest.approx(-6.02, abs=0.02)
    assert meter_level_to_dbfs(0.0) == -120.0
    assert meter_level_to_dbfs(None) is None


def test_summarize_meter_samples_drops_none_and_reduces():
    summary = summarize_meter_samples([0.5, None, 1.0, 0.25])

    assert summary["samples"] == 3
    assert summary["peak_level"] == 1.0
    assert summary["mean_level"] == pytest.approx((0.5 + 1.0 + 0.25) / 3, abs=1e-4)
    assert summary["peak_dbfs"] == 0.0


def test_summarize_meter_samples_all_none_is_none():
    assert summarize_meter_samples([None, None]) is None


def test_report_flags_peaks_over_ceiling():
    # Peaks at 1.0 -> 0 dBFS, target ceiling -1.0 dBTP -> 1 dB over.
    report = build_live_headroom_report([0.9, 1.0], get_target("edm"))

    assert report["read_only"] is True
    assert report["approximate"] is True
    assert report["target"]["name"] == "edm"
    assert report["peak_headroom_db"] == -1.0
    assert any("above the" in note and "ceiling" in note for note in report["guidance"])


def test_report_reports_headroom_under_ceiling():
    # Peak 0.5 -> ~-6 dBFS, ceiling -1.0 -> ~5 dB of headroom.
    report = build_live_headroom_report([0.4, 0.5], get_target("streaming"))

    assert report["peak_headroom_db"] == pytest.approx(5.02, abs=0.05)
    assert any("headroom under" in note for note in report["guidance"])


def test_report_mentions_loudness_proxy_and_steers_to_offline():
    report = build_live_headroom_report([0.5, 0.5], get_target("modern-pop"))

    assert any("uncalibrated loudness proxy" in note for note in report["guidance"])
    assert "compare_mix_to_target" in report["note"]


def test_report_handles_no_meter():
    report = build_live_headroom_report([None, None], get_target("rock"))

    assert report["meter"] is None
    assert report["peak_headroom_db"] is None
    assert any("No meter reading" in note for note in report["guidance"])
