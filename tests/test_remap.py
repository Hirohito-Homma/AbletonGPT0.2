"""Tests for diatonic/modal MIDI remap (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.remap import build_scale_remap_plan


def _clip(pitches, length=4.0):
    return {
        "length_beats": length,
        "notes": [
            {"pitch": p, "start_time": float(i) * 0.25, "duration": 0.25, "velocity": 100, "probability": 1.0}
            for i, p in enumerate(pitches)
        ],
    }


def _pitches(plan):
    return [n["pitch"] for n in plan["notes"]]


def test_major_to_parallel_minor_lowers_the_third():
    # C major triad C-E-G -> C minor triad C-Eb-G (degree function preserved).
    plan = build_scale_remap_plan(_clip([60, 64, 67]), 0, "major", 0, "minor")
    assert _pitches(plan) == [60, 63, 67]
    assert plan["changed_notes"] == 1  # only E moved
    assert plan["source_scale"] == "major" and plan["target_scale"] == "minor"


def test_same_key_and_scale_is_a_noop():
    plan = build_scale_remap_plan(_clip([60, 62, 64, 65, 67]), 0, "major", 0, "major")
    assert _pitches(plan) == [60, 62, 64, 65, 67]
    assert plan["changed_notes"] == 0


def test_same_scale_different_tonic_is_diatonic_transposition():
    # C major -> G major, both major: in-scale notes shift by a constant +7 (degree-locked).
    plan = build_scale_remap_plan(_clip([60, 64, 67]), 0, "major", 7, "major")
    assert _pitches(plan) == [67, 71, 74]  # C->G, E->B, G->D, each +7


def test_octave_is_preserved_relative_to_tonic():
    # A note below the tonic keeps its octave placement after the remap.
    plan = build_scale_remap_plan(_clip([59]), 0, "major", 0, "minor")  # B just below C4
    # B is degree 6 of C major (11); C minor degree 6 is 10 -> Bb, same octave band.
    assert _pitches(plan) == [58]


def test_out_of_scale_note_keeps_its_chromatic_offset():
    # C#4 (61): in C major nearest degree is C (0) with +1 delta; C minor degree 0 is C -> C#.
    plan = build_scale_remap_plan(_clip([61]), 0, "major", 0, "minor")
    assert _pitches(plan) == [61]  # tonic degree unchanged between major/minor, delta preserved


def test_preserves_timing_and_probability():
    clip = _clip([64])
    clip["notes"][0]["probability"] = 0.3
    plan = build_scale_remap_plan(clip, 0, "major", 0, "minor")
    note = plan["notes"][0]
    assert note["pitch"] == 63
    assert note["start_time"] == 0.0 and note["duration"] == 0.25
    assert note["probability"] == 0.3


def test_mismatched_degree_counts_rejected():
    with pytest.raises(ValueError, match="same"):
        build_scale_remap_plan(_clip([60]), 0, "major", 0, "major_pentatonic")


def test_pentatonic_to_pentatonic_allowed():
    plan = build_scale_remap_plan(_clip([60, 62, 64]), 0, "major_pentatonic", 9, "minor_pentatonic")
    assert plan["degree_count"] == 5
    assert plan["note_count"] == 3


def test_fingerprint_is_source_based():
    clip = _clip([60, 64])
    a = build_scale_remap_plan(clip, 0, "major", 0, "minor")["source_fingerprint"]
    b = build_scale_remap_plan(clip, 0, "major", 7, "major")["source_fingerprint"]
    assert a == b


def test_empty_clip_rejected():
    with pytest.raises(ValueError):
        build_scale_remap_plan({"length_beats": 4.0, "notes": []}, 0, "major", 0, "minor")
