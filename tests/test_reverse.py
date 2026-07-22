"""Tests for MIDI clip reverse / retrograde (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.reverse import build_reverse_plan


def _clip(events, length=4.0):
    # events: list of (pitch, start, duration)
    return {
        "length_beats": length,
        "notes": [
            {"pitch": p, "start_time": float(s), "duration": float(d), "velocity": 100, "probability": 1.0}
            for p, s, d in events
        ],
    }


def _events(plan):
    return [(n["pitch"], n["start_time"], n["duration"]) for n in plan["notes"]]


def test_reverse_mirrors_note_starts():
    # Note at 0.0-1.0 -> 3.0-4.0; note at 1.0-1.5 -> 2.5-3.0.
    plan = build_reverse_plan(_clip([(60, 0.0, 1.0), (62, 1.0, 0.5)], length=4.0))
    events = dict((p, (s, d)) for p, s, d in _events(plan))
    assert events[60] == (3.0, 1.0)
    assert events[62] == (2.5, 0.5)
    assert plan["length_beats"] == 4.0
    assert plan["note_count"] == 2


def test_note_filling_the_clip_maps_to_zero():
    plan = build_reverse_plan(_clip([(60, 0.0, 4.0)], length=4.0))
    assert _events(plan) == [(60, 0.0, 4.0)]


def test_symmetry_center_note_stays():
    # A note centered in the clip reverses onto itself.
    plan = build_reverse_plan(_clip([(60, 1.5, 1.0)], length=4.0))  # 1.5-2.5 -> 1.5-2.5
    assert _events(plan) == [(60, 1.5, 1.0)]


def test_pitch_velocity_probability_preserved():
    clip = _clip([(67, 0.0, 1.0)])
    clip["notes"][0]["velocity"] = 42
    clip["notes"][0]["probability"] = 0.9
    note = build_reverse_plan(clip)["notes"][0]
    assert note["pitch"] == 67
    assert note["velocity"] == 42
    assert note["probability"] == 0.9


def test_reverse_twice_is_identity():
    original = [(60, 0.0, 1.0), (62, 1.0, 0.5), (64, 2.75, 0.25)]
    once = build_reverse_plan(_clip(original, length=4.0))
    twice = build_reverse_plan({"length_beats": 4.0, "notes": once["notes"]})
    assert sorted(_events(twice)) == sorted(original)


def test_notes_stay_inside_the_clip():
    plan = build_reverse_plan(_clip([(60, 0.0, 1.0), (62, 3.5, 0.5)], length=4.0))
    for _pitch, start, duration in _events(plan):
        assert 0.0 <= start < 4.0
        assert start + duration <= 4.0 + 1e-9


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        build_reverse_plan({"length_beats": 4.0, "notes": []})
    with pytest.raises(ValueError):
        build_reverse_plan({"length_beats": 0.0, "notes": [{"pitch": 60, "start_time": 0.0, "duration": 1.0}]})
