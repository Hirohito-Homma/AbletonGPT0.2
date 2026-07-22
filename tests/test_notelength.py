"""Tests for note-length editing: legato and split (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.notelength import build_legato_plan, build_split_plan


def _clip(events, length=4.0):
    # events: list of (pitch, start, duration)
    return {
        "length_beats": length,
        "notes": [
            {"pitch": p, "start_time": float(s), "duration": float(d), "velocity": 100, "probability": 1.0}
            for p, s, d in events
        ],
    }


def _by_start(plan):
    return sorted(((n["pitch"], n["start_time"], n["duration"]) for n in plan["notes"]))


# --- legato ---


def test_legato_extends_to_next_same_pitch_onset():
    # Two C notes with a gap; the first extends to the second's onset.
    plan = build_legato_plan(_clip([(60, 0.0, 0.5), (60, 1.0, 0.5)], length=4.0))
    events = {(p, s): d for p, s, d in _by_start(plan)}
    assert events[(60, 0.0)] == 1.0  # extended 0.5 -> 1.0 (reaches the note at 1.0)
    assert events[(60, 1.0)] == 3.0  # last C extends to the clip end (4.0)
    assert plan["note_count"] == 2


def test_legato_gate_leaves_a_proportional_gap():
    plan = build_legato_plan(_clip([(60, 0.0, 0.25), (60, 1.0, 0.25)], length=4.0), gate=0.5)
    events = {(p, s): d for p, s, d in _by_start(plan)}
    assert events[(60, 0.0)] == 0.5  # half of the 1.0 gap


def test_legato_is_per_pitch():
    # Interleaved pitches: each extends to its own next onset, not the other's.
    plan = build_legato_plan(_clip([(60, 0.0, 0.25), (64, 0.5, 0.25), (60, 1.0, 0.25)], length=2.0))
    events = {(p, s): d for p, s, d in _by_start(plan)}
    assert events[(60, 0.0)] == 1.0  # to the next C at 1.0 (ignores the E at 0.5)
    assert events[(64, 0.5)] == 1.5  # E extends to the clip end (2.0)


def test_legato_preserves_pitch_and_velocity():
    clip = _clip([(67, 0.0, 0.5)])
    clip["notes"][0]["velocity"] = 55
    note = build_legato_plan(clip)["notes"][0]
    assert note["pitch"] == 67 and note["velocity"] == 55


def test_legato_bad_gate_rejected():
    with pytest.raises(ValueError):
        build_legato_plan(_clip([(60, 0.0, 0.5)]), gate=0.0)
    with pytest.raises(ValueError):
        build_legato_plan(_clip([(60, 0.0, 0.5)]), gate=1.5)


# --- split ---


def test_split_divides_each_note():
    plan = build_split_plan(_clip([(60, 0.0, 1.0)], length=4.0), divisions=4)
    assert plan["note_count"] == 4
    assert _by_start(plan) == [
        (60, 0.0, 0.25),
        (60, 0.25, 0.25),
        (60, 0.5, 0.25),
        (60, 0.75, 0.25),
    ]


def test_split_multiplies_note_count():
    plan = build_split_plan(_clip([(60, 0.0, 1.0), (62, 2.0, 1.0)], length=4.0), divisions=2)
    assert plan["source_note_count"] == 2
    assert plan["note_count"] == 4


def test_split_preserves_pitch_velocity_probability():
    clip = _clip([(60, 0.0, 1.0)])
    clip["notes"][0]["velocity"] = 88
    clip["notes"][0]["probability"] = 0.5
    plan = build_split_plan(clip, divisions=2)
    assert all(n["pitch"] == 60 and n["velocity"] == 88 and n["probability"] == 0.5 for n in plan["notes"])


def test_split_bad_divisions_rejected():
    with pytest.raises(ValueError):
        build_split_plan(_clip([(60, 0.0, 1.0)]), divisions=1)
    with pytest.raises(ValueError):
        build_split_plan(_clip([(60, 0.0, 1.0)]), divisions=32)


def test_split_note_ceiling():
    many = _clip([(60, i * 0.001, 0.001) for i in range(3000)], length=4.0)
    with pytest.raises(ValueError):
        build_split_plan(many, divisions=2)  # 6000 > 4096


def test_empty_clip_rejected():
    with pytest.raises(ValueError):
        build_legato_plan({"length_beats": 4.0, "notes": []})
    with pytest.raises(ValueError):
        build_split_plan({"length_beats": 4.0, "notes": []}, divisions=2)
