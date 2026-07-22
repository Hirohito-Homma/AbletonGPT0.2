"""Tests for half-time / double-time clip conversion (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.timescale import build_timescale_plan, factor_for


def _clip(events, length=4.0):
    # events: list of (start, duration)
    return {
        "length_beats": length,
        "clip": "Part",
        "notes": [
            {"pitch": 60, "start_time": float(s), "duration": float(d), "velocity": 100, "probability": 1.0}
            for s, d in events
        ],
    }


def test_factor_for_named_modes():
    assert factor_for("half") == 2.0
    assert factor_for("Double") == 0.5
    assert factor_for("half-time") == 2.0
    assert factor_for("double_time") == 0.5
    with pytest.raises(ValueError):
        factor_for("triple")


def test_half_time_doubles_timing_and_length():
    plan = build_timescale_plan(_clip([(0.0, 1.0), (2.0, 0.5)], length=4.0), factor=2.0)
    assert plan["length_beats"] == 8.0
    events = [(n["start_time"], n["duration"]) for n in plan["notes"]]
    assert events == [(0.0, 2.0), (4.0, 1.0)]
    assert plan["note_count"] == 2


def test_double_time_halves_timing_and_length():
    plan = build_timescale_plan(_clip([(0.0, 1.0), (2.0, 1.0)], length=4.0), factor=0.5)
    assert plan["length_beats"] == 2.0
    events = [(n["start_time"], n["duration"]) for n in plan["notes"]]
    assert events == [(0.0, 0.5), (1.0, 0.5)]


def test_pitch_velocity_probability_preserved():
    clip = _clip([(1.0, 1.0)])
    clip["notes"][0]["velocity"] = 77
    clip["notes"][0]["probability"] = 0.4
    plan = build_timescale_plan(clip, factor=2.0)
    note = plan["notes"][0]
    assert note["pitch"] == 60
    assert note["velocity"] == 77
    assert note["probability"] == 0.4


def test_notes_fit_inside_the_new_length():
    plan = build_timescale_plan(_clip([(3.0, 1.0)], length=4.0), factor=2.0)
    for note in plan["notes"]:
        assert note["start_time"] + note["duration"] <= plan["length_beats"] + 1e-9


def test_fingerprint_is_source_based():
    clip = _clip([(0.0, 1.0)])
    a = build_timescale_plan(clip, factor=2.0)["source_fingerprint"]
    b = build_timescale_plan(clip, factor=0.5)["source_fingerprint"]
    assert a == b


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        build_timescale_plan(_clip([(0.0, 1.0)]), factor=0.0)
    with pytest.raises(ValueError):
        build_timescale_plan({"length_beats": 4.0, "notes": []}, factor=2.0)
    with pytest.raises(ValueError):
        build_timescale_plan(_clip([(0.0, 1.0)], length=3000.0), factor=2.0)  # would exceed 4096
