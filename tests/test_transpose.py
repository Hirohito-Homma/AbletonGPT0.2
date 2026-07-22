"""Tests for MIDI clip transposition (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.transpose import build_transpose_plan, shift_to_target_pc


def _clip(pitches, length=4.0):
    return {
        "length_beats": length,
        "notes": [
            {"pitch": p, "start_time": float(i), "duration": 1.0, "velocity": 100, "probability": 1.0}
            for i, p in enumerate(pitches)
        ],
    }


def test_shift_to_target_pc_directions():
    # C (0) -> G (7): nearest goes down a fourth (-5), up goes +7, down goes -5.
    assert shift_to_target_pc(0, 7, "nearest") == -5
    assert shift_to_target_pc(0, 7, "up") == 7
    assert shift_to_target_pc(0, 7, "down") == -5
    # C -> D (2): nearest +2.
    assert shift_to_target_pc(0, 2, "nearest") == 2
    # Tritone C -> F# (6): nearest rounds up to +6.
    assert shift_to_target_pc(0, 6, "nearest") == 6
    # Same pitch class: 0 in every direction.
    assert shift_to_target_pc(5, 5, "up") == 0
    assert shift_to_target_pc(5, 5, "down") == 0


def test_shift_rejects_bad_direction():
    with pytest.raises(ValueError):
        shift_to_target_pc(0, 5, "sideways")


def test_transpose_shifts_every_pitch_and_keeps_count():
    plan = build_transpose_plan(_clip([60, 64, 67]), 2)

    assert plan["semitones"] == 2
    assert [n["pitch"] for n in plan["notes"]] == [62, 66, 69]
    assert plan["note_count"] == 3
    assert plan["folded_notes"] == 0
    assert plan["result_pitch_range"] == {"lowest": 62, "highest": 69}


def test_transpose_preserves_timing_and_probability():
    clip = _clip([60])
    clip["notes"][0]["probability"] = 0.5
    plan = build_transpose_plan(clip, -3)

    note = plan["notes"][0]
    assert note["pitch"] == 57
    assert note["start_time"] == 0.0
    assert note["duration"] == 1.0
    assert note["probability"] == 0.5


def test_out_of_range_notes_are_octave_folded():
    # 125 + 5 = 130 -> folds down to 118 (still C#... same pitch class as 130 % 12).
    plan = build_transpose_plan(_clip([125]), 5)
    assert plan["folded_notes"] == 1
    assert plan["notes"][0]["pitch"] == 118
    assert 0 <= plan["notes"][0]["pitch"] <= 127
    assert plan["notes"][0]["pitch"] % 12 == 130 % 12


def test_low_notes_fold_up():
    plan = build_transpose_plan(_clip([2]), -5)  # -3 -> folds up to 9
    assert plan["notes"][0]["pitch"] == 9
    assert plan["folded_notes"] == 1


def test_fingerprint_is_stable_and_shift_independent():
    clip = _clip([60, 64])
    a = build_transpose_plan(clip, 0)["source_fingerprint"]
    b = build_transpose_plan(clip, 7)["source_fingerprint"]
    assert a == b  # fingerprint is of the SOURCE, not the result


def test_empty_clip_and_bad_shift_rejected():
    with pytest.raises(ValueError):
        build_transpose_plan({"length_beats": 4.0, "notes": []}, 2)
    with pytest.raises(ValueError):
        build_transpose_plan(_clip([60]), 99)
