"""Tests for Roman-numeral / functional chord-progression analysis (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.progression import (
    build_progression_analysis,
    identify_chord,
)


def _triad_notes(chords, chord_beats=4.0):
    """One block triad per window; ``chords`` is a list of pitch tuples."""
    notes = []
    for i, pitches in enumerate(chords):
        for pitch in pitches:
            notes.append(
                {
                    "pitch": pitch,
                    "start_time": i * chord_beats,
                    "duration": chord_beats,
                    "velocity": 100,
                    "probability": 1.0,
                }
            )
    return {"length_beats": len(chords) * chord_beats, "notes": notes, "time_signature": [4, 4]}


def _weights(pcs):
    return {pc: 1.0 for pc in pcs}


def test_identify_major_and_minor_triads():
    cmaj = identify_chord(_weights([0, 4, 7]))
    assert cmaj["root"] == 0 and cmaj["quality"] == "maj" and cmaj["complete"] is True

    amin = identify_chord(_weights([9, 0, 4]))
    assert amin["root"] == 9 and amin["quality"] == "min"


def test_identify_dominant_seventh_over_triad():
    g7 = identify_chord(_weights([7, 11, 2, 5]))  # G B D F
    assert g7["root"] == 7 and g7["quality"] == "dom7"


def test_identify_returns_none_for_silence():
    assert identify_chord({}) is None


def test_incomplete_triad_flagged():
    # Just a root+fifth (power chord): not a complete triad.
    dyad = identify_chord(_weights([0, 7]))
    assert dyad["complete"] is False


def test_progression_roman_numerals_in_c_major():
    # C - G - Am - F  ->  I - V - vi - IV
    clip = _triad_notes([(60, 64, 67), (67, 71, 74), (69, 72, 76), (65, 69, 72)])
    report = build_progression_analysis(clip, 0, "major", 4.0)

    assert report["key"] == "C major"
    assert report["romans"] == ["I", "V", "vi", "IV"]
    assert report["progression"] == "I - V - vi - IV"
    functions = [s["function"] for s in report["segments"]]
    assert functions == ["tonic", "dominant", "tonic", "subdominant"]


def test_progression_minor_key_numerals():
    # A minor: Am - Dm - E(major, dominant) -> i - iv - V
    clip = _triad_notes([(69, 72, 76), (62, 65, 69), (64, 68, 71)])
    report = build_progression_analysis(clip, 9, "minor", 4.0)

    assert report["romans"] == ["i", "iv", "V"]
    assert [s["function"] for s in report["segments"]] == ["tonic", "subdominant", "dominant"]


def test_chromatic_root_gets_accidental_and_chromatic_function():
    # Eb major triad in C major -> bIII, chromatic.
    clip = _triad_notes([(63, 67, 70)])
    report = build_progression_analysis(clip, 0, "major", 4.0)
    segment = report["segments"][0]
    assert segment["roman"] == "bIII"
    assert segment["function"] == "chromatic"


def test_consecutive_identical_chords_merge_in_summary():
    clip = _triad_notes([(60, 64, 67), (60, 64, 67), (67, 71, 74)])
    report = build_progression_analysis(clip, 0, "major", 4.0)
    assert report["romans"] == ["I", "V"]  # the repeated I collapses
    assert report["segment_count"] == 3  # but all three segments are still listed


def test_rest_window_reported_as_rest():
    clip = {
        "length_beats": 8.0,
        "notes": [{"pitch": 60, "start_time": 0.0, "duration": 4.0, "velocity": 100, "probability": 1.0}],
        "time_signature": [4, 4],
    }
    report = build_progression_analysis(clip, 0, "major", 4.0)
    assert report["segments"][1]["function"] == "rest"
    assert report["segments"][1]["roman"] is None
    assert "·" in report["romans"]


def test_bad_inputs_rejected():
    clip = _triad_notes([(60, 64, 67)])
    with pytest.raises(ValueError):
        build_progression_analysis(clip, 0, "dorian", 4.0)  # mode must be major/minor
    with pytest.raises(ValueError):
        build_progression_analysis(clip, 0, "major", 0.0)  # segment_beats > 0
    with pytest.raises(ValueError):
        build_progression_analysis({"length_beats": 4.0, "notes": []}, 0, "major", 4.0)
