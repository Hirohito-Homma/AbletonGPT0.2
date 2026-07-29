"""Tests for the narrative-arc engine (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.narrative import build_narrative_arc


def _by_position(arc):
    return {section["position"]: section for section in arc["sections"]}


def test_intro_is_low_and_chorus_is_high():
    arc = build_narrative_arc(["Intro", "Verse", "Chorus"])
    sections = _by_position(arc)
    assert sections[0]["archetype"] == "intro"
    assert sections[2]["archetype"] == "chorus"
    # Energy climbs from the intro to the chorus.
    assert sections[0]["energy"] < sections[1]["energy"] < sections[2]["energy"]


def test_build_ramps_toward_the_following_chorus():
    arc = build_narrative_arc(["Verse", "Build", "Chorus"])
    sections = _by_position(arc)
    verse, build, chorus = sections[0], sections[1], sections[2]
    # A build sits between the verse and the chorus it sets up, and rises.
    assert verse["energy"] < build["energy"] < chorus["energy"]
    assert build["tension"] == "rise"
    assert build["directives"]["dynamics"] == "crescendo"
    assert build["directives"]["motion"] == "riser+fill into next"


def test_returning_chorus_grows_and_is_marked_to_vary():
    arc = build_narrative_arc(["Chorus", "Verse", "Chorus"])
    sections = _by_position(arc)
    first, second = sections[0], sections[2]
    assert second["energy"] >= first["energy"]  # the returning chorus is at least as big
    assert second["directives"]["vary"] is True  # ...and should be varied, not photocopied
    assert first["directives"]["vary"] is False


def test_breakdown_then_chorus_contrast_and_roles():
    arc = build_narrative_arc(["Chorus", "Breakdown", "Chorus"])
    sections = _by_position(arc)
    breakdown = sections[1]
    final_chorus = sections[2]
    assert breakdown["role"] == "reset"
    assert breakdown["tension"] == "fall"
    assert breakdown["directives"]["density"] == "sparse"
    # The chorus that lands after the breakdown is the loudest thing in the tune.
    assert final_chorus["energy"] == max(arc["energy_curve"])
    assert final_chorus["role"] == "climax"


def test_peak_and_shape_reported():
    arc = build_narrative_arc(["Intro", "Verse", "Build", "Chorus", "Outro"])
    assert arc["section_count"] == 5
    assert arc["peak_label"] == "Chorus"
    assert arc["peak_position"] == arc["energy_curve"].index(max(arc["energy_curve"]))
    assert arc["shape"] in ("arch", "climactic", "front-loaded")


def test_first_section_opens_and_directives_present():
    arc = build_narrative_arc(["Intro"])
    section = arc["sections"][0]
    assert section["tension"] == "open"
    assert section["role"] == "setup"
    directives = section["directives"]
    assert set(directives) == {
        "density",
        "dynamics",
        "register",
        "motion",
        "target_velocity",
        "vary",
    }
    assert 1 <= directives["target_velocity"] <= 127
    assert isinstance(section["advice"], str) and section["advice"]


def test_unknown_label_defaults_to_full_archetype():
    # layering.section_archetype maps an unknown label to the full-arrangement default (chorus).
    arc = build_narrative_arc(["Weird Section"])
    assert arc["sections"][0]["archetype"] == "chorus"


def test_energy_curve_matches_sections_and_stays_in_range():
    arc = build_narrative_arc(["Intro", "Verse", "Chorus", "Breakdown", "Chorus", "Outro"])
    curve = arc["energy_curve"]
    assert curve == [section["energy"] for section in arc["sections"]]
    assert all(0.0 <= value <= 1.0 for value in curve)


def test_empty_structure_rejected():
    with pytest.raises(ValueError):
        build_narrative_arc([])
