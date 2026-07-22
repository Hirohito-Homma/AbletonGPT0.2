"""Tests for building a phrase from a MIDI loop (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.phrase import build_phrase_from_loop


def _loop(notes, length=4.0, signature=(4, 4)):
    return {
        "length_beats": length,
        "time_signature": list(signature),
        "clip": "Loop",
        "notes": [dict(n) for n in notes],
    }


def _kick_loop():
    # Two hits per bar at beats 0 and 2, duration 0.5.
    return _loop(
        [
            {"pitch": 36, "start_time": 0.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
            {"pitch": 36, "start_time": 2.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        ]
    )


def test_tiling_repeats_the_loop():
    plan = build_phrase_from_loop(_kick_loop(), repeats=3)

    assert plan["length_beats"] == 12.0
    assert plan["note_count"] == 6  # 2 notes x 3
    starts = sorted(n["start_time"] for n in plan["notes"])
    assert starts == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]


def test_single_repeat_is_a_copy():
    plan = build_phrase_from_loop(_kick_loop(), repeats=1)
    assert plan["length_beats"] == 4.0
    assert plan["note_count"] == 2


def test_build_up_ramps_velocities_up_over_the_phrase():
    plan = build_phrase_from_loop(_kick_loop(), repeats=4, build_up=1.0)
    by_start = sorted(plan["notes"], key=lambda n: n["start_time"])
    vels = [n["velocity"] for n in by_start]
    assert vels == sorted(vels)  # non-decreasing
    assert vels[0] < vels[-1]
    assert all(1 <= v <= 127 for v in vels)


def test_final_fill_adds_notes_in_the_last_bar_only():
    plan = build_phrase_from_loop(_kick_loop(), repeats=2, final_fill=True)
    # 4 tiled notes + a subdivision of the 2 notes in the last bar.
    assert plan["added_fill_notes"] == 2
    assert plan["note_count"] == 6
    fill_starts = sorted(n["start_time"] for n in plan["notes"])
    # The subdivisions land at 4.25 and 6.25 (mid of the last-bar notes at 4.0 and 6.0).
    assert 4.25 in fill_starts and 6.25 in fill_starts
    # No fill note before the last bar (starts at 4.0).
    assert all(n["start_time"] >= 4.0 for n in plan["notes"] if n["duration"] == 0.25)


def test_fill_notes_stay_inside_the_clip():
    plan = build_phrase_from_loop(_kick_loop(), repeats=2, final_fill=True)
    for note in plan["notes"]:
        assert note["start_time"] + note["duration"] <= plan["length_beats"] + 1e-9


def test_source_note_pitches_preserved():
    plan = build_phrase_from_loop(_kick_loop(), repeats=2)
    assert {n["pitch"] for n in plan["notes"]} == {36}


def test_fingerprint_is_source_based():
    loop = _kick_loop()
    a = build_phrase_from_loop(loop, repeats=2)["source_fingerprint"]
    b = build_phrase_from_loop(loop, repeats=4, build_up=0.5)["source_fingerprint"]
    assert a == b


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        build_phrase_from_loop(_kick_loop(), repeats=0)
    with pytest.raises(ValueError):
        build_phrase_from_loop(_kick_loop(), repeats=2, build_up=1.5)
    with pytest.raises(ValueError):
        build_phrase_from_loop({"length_beats": 4.0, "notes": []}, repeats=2)
    with pytest.raises(ValueError):
        build_phrase_from_loop(_loop([{"pitch": 36, "start_time": 0.0, "duration": 1.0, "velocity": 100}], length=2000.0), repeats=4)
