"""Tests for the per-section frequency-band + stereo treatment engine (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.section_spectral import BANDS, build_section_spectral_plan


def _by_position(plan):
    return {section["position"]: section for section in plan["sections"]}


def test_band_balance_sums_to_one_and_covers_all_bands():
    plan = build_section_spectral_plan(["Intro", "Verse", "Chorus"])
    for section in plan["sections"]:
        assert set(section["band_balance"]) == set(BANDS)
        assert abs(sum(section["band_balance"].values()) - 1.0) < 1e-6
        assert set(section["gain_db"]) == set(BANDS)
        assert set(section["treatment"]) == set(BANDS)


def test_intro_is_high_passed_and_not_mono_locked():
    plan = build_section_spectral_plan(["Intro"])
    intro = plan["sections"][0]
    # Low cut, top lifted -> filtered / airy.
    assert intro["gain_db"]["low"] < 0 and intro["treatment"]["low"] == "cut"
    assert intro["gain_db"]["high"] > 0 and intro["treatment"]["high"] == "boost"
    # Heavily high-passed, so there is little sub to keep mono.
    assert intro["low_mono"] is False


def test_breakdown_is_narrow_and_low_cut():
    plan = build_section_spectral_plan(["Chorus", "Breakdown"])
    breakdown = _by_position(plan)[1]
    assert breakdown["stereo"] == "narrow"
    assert breakdown["gain_db"]["low"] < 0  # sub pulled down for intimacy
    assert breakdown["gain_db"]["mid"] >= 0  # mid-focused


def test_chorus_is_wide_full_and_low_mono():
    plan = build_section_spectral_plan(["Verse", "Chorus"])
    chorus = _by_position(plan)[1]
    assert chorus["stereo"] == "wide"
    assert chorus["gain_db"]["low"] > 0  # full low end
    assert chorus["low_mono"] is True  # real low content -> keep it mono


def test_width_widens_with_energy_across_repeats():
    # A returning chorus carries more energy, so it should be at least as wide.
    plan = build_section_spectral_plan(["Chorus", "Verse", "Chorus"])
    sections = _by_position(plan)
    assert sections[2]["stereo_width"] >= sections[0]["stereo_width"]


def test_gain_db_is_clamped_and_advice_present():
    plan = build_section_spectral_plan(["Intro", "Chorus", "Breakdown"])
    for section in plan["sections"]:
        for value in section["gain_db"].values():
            assert -6.0 <= value <= 6.0
        assert isinstance(section["advice"], str) and section["advice"]


def test_neutral_baseline_reported_and_read_only():
    plan = build_section_spectral_plan(["Verse"])
    assert plan["read_only"] is True
    assert abs(sum(plan["neutral_baseline"].values()) - 1.0) < 1e-6
    assert plan["bands"] == list(BANDS)


def test_empty_structure_rejected():
    with pytest.raises(ValueError):
        build_section_spectral_plan([])
