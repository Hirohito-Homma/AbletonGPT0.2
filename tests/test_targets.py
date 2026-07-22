"""Tests for the built-in genre mix/master targets (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.reference import build_reference_comparison
from abletongpt.targets import GENRE_TARGETS, get_target, list_targets


def test_list_targets_returns_all_with_summary_fields():
    rows = list_targets()

    assert len(rows) == len(GENRE_TARGETS)
    names = {row["name"] for row in rows}
    assert {"streaming", "modern-pop", "edm", "hip-hop", "classical", "podcast"} <= names
    for row in rows:
        assert set(row) == {"name", "description", "integrated_lufs"}
        assert isinstance(row["description"], str) and row["description"]


def test_every_target_band_fractions_sum_to_one():
    for name, target in GENRE_TARGETS.items():
        total = sum(target["bands"].values())
        assert total == pytest.approx(1.0), "%s bands sum to %r" % (name, total)
        assert set(target["bands"]) == {"low", "low_mid", "mid", "high_mid", "high"}


def test_every_target_carries_the_loudness_fields():
    for name, target in GENRE_TARGETS.items():
        for field in ("integrated_lufs", "loudness_range_lu", "true_peak_dbtp", "crest_factor_db"):
            assert isinstance(target[field], float), "%s missing %s" % (name, field)


def test_get_target_returns_a_comparator_ready_profile():
    profile = get_target("modern-pop")

    assert profile["target"] == "modern-pop"
    assert profile["integrated_lufs"] == GENRE_TARGETS["modern-pop"]["integrated_lufs"]
    assert profile["bands"]["low"] == GENRE_TARGETS["modern-pop"]["bands"]["low"]


def test_get_target_name_is_normalized():
    assert get_target("Modern Pop")["target"] == "modern-pop"
    assert get_target("modern_pop")["target"] == "modern-pop"
    assert get_target("  EDM  ")["target"] == "edm"


def test_get_target_is_a_copy_not_the_backing_dict():
    profile = get_target("edm")
    profile["bands"]["low"] = 0.99

    assert GENRE_TARGETS["edm"]["bands"]["low"] != 0.99


def test_get_target_unknown_lists_available_names():
    with pytest.raises(KeyError) as excinfo:
        get_target("dubstep")

    message = str(excinfo.value)
    assert "dubstep" in message
    assert "modern-pop" in message


def test_target_profile_feeds_the_reference_comparator():
    # A quiet, dark mix vs the loud EDM target: should flag quieter + low-energy gaps.
    mix = {
        "integrated_lufs": -14.0,
        "loudness_range_lu": 9.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 12.0,
        "bands": {"low": 0.22, "low_mid": 0.28, "mid": 0.28, "high_mid": 0.14, "high": 0.08},
    }
    report = build_reference_comparison(mix, get_target("edm"))

    assert report["read_only"] is True
    # -14 vs the -7.5 EDM target -> 6.5 LU quieter.
    assert report["deltas"]["loudness_lu"] == pytest.approx(-6.5)
    assert any("quieter" in note for note in report["guidance"])
    # Mix has less low energy than the bass-forward target.
    assert report["deltas"]["bands"]["low"] < 0
    assert any("less low energy" in note for note in report["guidance"])
    # Tone/stereo are unset on targets, so those dimensions are skipped in the score.
    assert "tone" not in report["match"]["dimensions"]
    assert "stereo" not in report["match"]["dimensions"]
    assert 0.0 <= report["match"]["score"] <= 100.0
