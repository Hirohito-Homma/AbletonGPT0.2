"""Tests for developing a loop into a narrative arrangement (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.develop import build_developed_arrangement


_LOOP = {
    "clip": "Riff",
    "length_beats": 4.0,
    "time_signature": [4, 4],
    "notes": [
        {"pitch": 48, "start_time": 0.0, "duration": 0.5, "velocity": 90, "probability": 1.0},
        {"pitch": 60, "start_time": 0.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        {"pitch": 64, "start_time": 1.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        {"pitch": 67, "start_time": 2.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        {"pitch": 72, "start_time": 3.0, "duration": 0.5, "velocity": 80, "probability": 1.0},
    ],
}


def _sections(plan):
    return {section["archetype"]: section for section in plan["sections"]}


def test_length_and_contiguous_sections():
    plan = build_developed_arrangement(_LOOP, ["Intro", "Verse", "Chorus"], section_repeats=2)
    assert plan["read_only"] is True
    # 4-beat loop x2 repeats x3 sections.
    assert plan["length_beats"] == 24.0
    assert plan["section_length_beats"] == 8.0
    sections = plan["sections"]
    assert [s["label"] for s in sections] == ["Intro", "Verse", "Chorus"]
    # Sections are laid end to end with no gaps or overlaps.
    for earlier, later in zip(sections, sections[1:]):
        assert earlier["end_beat"] == later["start_beat"]
    assert plan["source_fingerprint"]
    assert plan["source_note_count"] == 5


def test_chorus_is_denser_than_intro():
    plan = build_developed_arrangement(_LOOP, ["Intro", "Chorus"], section_repeats=2)
    sections = _sections(plan)
    # A sparse intro is thinned; a full chorus is filled + octave-doubled.
    assert sections["chorus"]["note_count"] > sections["intro"]["note_count"]


def test_chorus_octave_doubles_the_top():
    plan = build_developed_arrangement(_LOOP, ["Chorus"], section_repeats=1)
    chorus_notes = [n for n in plan["notes"] if plan["sections"][0]["start_beat"] <= n["start_time"]]
    source_max = max(n["pitch"] for n in _LOOP["notes"])
    # Doubling the top voice puts notes above the source's highest pitch.
    assert any(n["pitch"] > source_max for n in chorus_notes)


def test_breakdown_drops_the_low_voices():
    plan = build_developed_arrangement(_LOOP, ["Chorus", "Breakdown"], section_repeats=1)
    breakdown = _sections(plan)["breakdown"]
    start, end = breakdown["start_beat"], breakdown["end_beat"]
    low = [n for n in plan["notes"] if start <= n["start_time"] < end and n["pitch"] < 60]
    # The low pitches (48, 60 is at the median) are stripped for an intimate breakdown.
    assert all(n["pitch"] >= 60 for n in plan["notes"] if start <= n["start_time"] < end)
    assert low == []


def test_returning_section_is_varied():
    plan = build_developed_arrangement(_LOOP, ["Chorus", "Verse", "Chorus"], section_repeats=2)
    sections = plan["sections"]
    first_chorus, second_chorus = sections[0], sections[2]
    assert first_chorus["applied"]["vary"] is False
    assert second_chorus["applied"]["vary"] is True
    # The varied return is thinned, so it differs from the first appearance.
    assert second_chorus["note_count"] <= first_chorus["note_count"]


def test_deterministic_for_same_seed():
    a = build_developed_arrangement(_LOOP, ["Intro", "Build", "Chorus"], section_repeats=2, seed=7)
    b = build_developed_arrangement(_LOOP, ["Intro", "Build", "Chorus"], section_repeats=2, seed=7)
    assert a["notes"] == b["notes"]


def test_energy_curve_carried_from_arc():
    plan = build_developed_arrangement(_LOOP, ["Intro", "Verse", "Chorus", "Outro"], section_repeats=1)
    assert plan["energy_curve"] == [s["energy"] for s in plan["sections"]]
    assert plan["peak_label"] == "Chorus"


def test_velocities_stay_in_range():
    plan = build_developed_arrangement(_LOOP, ["Intro", "Build", "Chorus", "Breakdown"], section_repeats=2)
    assert all(1 <= n["velocity"] <= 127 for n in plan["notes"])


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        build_developed_arrangement(_LOOP, [], section_repeats=2)
    with pytest.raises(ValueError):
        build_developed_arrangement({"length_beats": 4.0, "notes": []}, ["Verse"])
    with pytest.raises(ValueError):
        build_developed_arrangement(_LOOP, ["Verse"], section_repeats=0)
    with pytest.raises(ValueError):
        build_developed_arrangement({"length_beats": 0.0, "notes": _LOOP["notes"]}, ["Verse"])
