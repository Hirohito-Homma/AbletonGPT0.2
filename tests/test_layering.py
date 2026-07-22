"""Tests for section-based layering / mute planning (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.layering import (
    build_layering_plan,
    infer_track_role,
    section_archetype,
)


def test_infer_track_role_by_keyword():
    assert infer_track_role("Kick") == "drums"
    assert infer_track_role("Drum Rack") == "drums"
    assert infer_track_role("Sub Bass") == "bass"
    assert infer_track_role("808") == "bass"
    assert infer_track_role("Lead Synth") == "lead"
    assert infer_track_role("Warm Pad") == "pad"
    assert infer_track_role("Lead Vox") == "vocal"  # 'vox' wins over 'lead' by keyword order
    assert infer_track_role("Piano") == "chords"
    assert infer_track_role("Riser FX") == "fx"
    assert infer_track_role("Congas") == "perc"
    assert infer_track_role("Mystery") == "chords"  # fallback


def test_section_archetype_matching():
    assert section_archetype("Intro") == "intro"
    assert section_archetype("Verse 1") == "verse"
    assert section_archetype("Pre-Chorus") == "build"  # 'pre' before 'chorus'
    assert section_archetype("Chorus") == "chorus"
    assert section_archetype("Drop") == "chorus"
    assert section_archetype("Breakdown") == "breakdown"  # before 'bridge'/'chorus'
    assert section_archetype("Bridge") == "bridge"
    assert section_archetype("Outro") == "outro"
    assert section_archetype("Weird Section") == "chorus"  # default is full


_TRACKS = [
    {"index": 0, "name": "Kick"},
    {"index": 1, "name": "Bass"},
    {"index": 2, "name": "Piano"},
    {"index": 3, "name": "Lead"},
    {"index": 4, "name": "Pad"},
    {"index": 5, "name": "Vox"},
]


def _section(plan, label):
    return next(s for s in plan["sections"] if s["label"] == label)


def test_intro_is_sparse_and_chorus_is_full():
    plan = build_layering_plan(["Intro", "Chorus"], _TRACKS)

    intro = _section(plan, "Intro")
    assert set(intro["active_tracks"]) == {"Piano", "Pad"}  # chords + pad
    assert "Kick" in intro["muted_tracks"] and "Bass" in intro["muted_tracks"]

    chorus = _section(plan, "Chorus")
    assert chorus["muted_tracks"] == []  # everything plays in the chorus


def test_breakdown_drops_drums_and_bass():
    plan = build_layering_plan(["Breakdown"], _TRACKS)
    breakdown = _section(plan, "Breakdown")
    assert "Kick" in breakdown["muted_tracks"]
    assert "Bass" in breakdown["muted_tracks"]
    assert "Pad" in breakdown["active_tracks"]


def test_role_override_changes_activity():
    tracks = [{"index": 0, "name": "Ambiguous", "role": "drums"}]
    plan = build_layering_plan(["Intro"], tracks)
    # As drums, it is muted in the sparse intro.
    assert plan["sections"][0]["muted_tracks"] == ["Ambiguous"]
    assert plan["tracks"][0]["role"] == "drums"


def test_layers_carry_per_track_flags():
    plan = build_layering_plan(["Intro"], _TRACKS)
    layers = {layer["name"]: layer for layer in plan["sections"][0]["layers"]}
    assert layers["Piano"]["active"] is True
    assert layers["Kick"]["active"] is False
    assert layers["Kick"]["role"] == "drums"


def test_position_index_is_recorded():
    plan = build_layering_plan(["Intro", "Verse", "Chorus"], _TRACKS)
    assert [s["position"] for s in plan["sections"]] == [0, 1, 2]


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        build_layering_plan([], _TRACKS)
    with pytest.raises(ValueError):
        build_layering_plan(["Intro"], [])
