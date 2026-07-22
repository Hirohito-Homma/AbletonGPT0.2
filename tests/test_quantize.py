"""Tests for MIDI timing quantization (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.quantize import build_quantize_plan


def _clip(starts, length=4.0, duration=0.25):
    return {
        "length_beats": length,
        "notes": [
            {"pitch": 60 + i, "start_time": float(s), "duration": duration, "velocity": 100, "probability": 1.0}
            for i, s in enumerate(starts)
        ],
    }


def _starts(plan):
    return [n["start_time"] for n in plan["notes"]]


def test_full_strength_snaps_to_nearest_grid():
    plan = build_quantize_plan(_clip([0.06, 0.47, 0.98, 1.52]), grid_beats=0.5, strength=1.0)
    assert _starts(plan) == [0.0, 0.5, 1.0, 1.5]
    assert plan["moved_notes"] == 4


def test_in_grid_notes_do_not_move():
    plan = build_quantize_plan(_clip([0.0, 0.5, 1.0, 2.0]), grid_beats=0.5, strength=1.0)
    assert _starts(plan) == [0.0, 0.5, 1.0, 2.0]
    assert plan["moved_notes"] == 0


def test_partial_strength_moves_halfway():
    # start 0.10 toward grid 0.0 at strength 0.5 -> 0.05.
    plan = build_quantize_plan(_clip([0.10]), grid_beats=0.5, strength=0.5)
    assert _starts(plan) == [0.05]


def test_zero_strength_is_a_noop():
    plan = build_quantize_plan(_clip([0.13, 0.41]), grid_beats=0.5, strength=0.0)
    assert _starts(plan) == [0.13, 0.41]
    assert plan["moved_notes"] == 0


def test_swing_pushes_odd_grid_positions_later():
    # Grid 0.5: index 0 (0.0) stays, index 1 (0.5) is the off-beat -> pushed by swing*grid/2.
    plan = build_quantize_plan(_clip([0.0, 0.5]), grid_beats=0.5, strength=1.0, swing=0.5)
    assert _starts(plan)[0] == 0.0
    assert _starts(plan)[1] == pytest.approx(0.5 + 0.5 * 0.25)  # 0.625


def test_notes_never_snap_to_the_clip_end():
    # A note at 3.9 in a 4-beat clip must snap back to 3.5, not up to 4.0.
    plan = build_quantize_plan(_clip([3.9]), grid_beats=0.5, strength=1.0)
    assert _starts(plan) == [3.5]
    assert all(0.0 <= s < 4.0 for s in _starts(plan))


def test_preserves_pitch_duration_velocity_probability():
    clip = _clip([0.13])
    clip["notes"][0]["probability"] = 0.7
    plan = build_quantize_plan(clip, grid_beats=0.25, strength=1.0)
    note = plan["notes"][0]
    assert note["pitch"] == 60
    assert note["duration"] == 0.25
    assert note["velocity"] == 100
    assert note["probability"] == 0.7


def test_shift_stats_reported():
    plan = build_quantize_plan(_clip([0.1, 0.6]), grid_beats=0.5, strength=1.0)
    # 0.1 -> 0.0 (shift 0.1), 0.6 -> 0.5 (shift 0.1)
    assert plan["max_abs_shift_beats"] == pytest.approx(0.1)
    assert plan["average_abs_shift_beats"] == pytest.approx(0.1)


def test_fingerprint_is_source_based():
    clip = _clip([0.1, 0.6])
    a = build_quantize_plan(clip, grid_beats=0.5)["source_fingerprint"]
    b = build_quantize_plan(clip, grid_beats=0.25)["source_fingerprint"]
    assert a == b


def test_bad_parameters_rejected():
    with pytest.raises(ValueError):
        build_quantize_plan(_clip([0.1]), grid_beats=0.0)
    with pytest.raises(ValueError):
        build_quantize_plan(_clip([0.1]), grid_beats=0.5, strength=1.5)
    with pytest.raises(ValueError):
        build_quantize_plan(_clip([0.1]), grid_beats=0.5, swing=-0.1)
    with pytest.raises(ValueError):
        build_quantize_plan({"length_beats": 4.0, "notes": []}, grid_beats=0.5)
    with pytest.raises(ValueError):
        build_quantize_plan(_clip([0.1], length=2.0), grid_beats=4.0)  # grid > length
