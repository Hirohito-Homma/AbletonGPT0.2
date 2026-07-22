"""Tests for velocity groove/dynamics shaping (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.groove import build_velocity_groove_plan


def _clip(velocities, length=4.0, starts=None):
    starts = starts if starts is not None else [float(i) for i in range(len(velocities))]
    return {
        "length_beats": length,
        "notes": [
            {"pitch": 60, "start_time": float(s), "duration": 0.5, "velocity": int(v), "probability": 1.0}
            for s, v in zip(starts, velocities)
        ],
    }


def _vels(plan):
    # Sorted by start_time in the plan; recover by original order via start_time.
    return [n["velocity"] for n in sorted(plan["notes"], key=lambda n: n["start_time"])]


def test_all_defaults_is_a_noop():
    plan = build_velocity_groove_plan(_clip([80, 90, 100]))
    assert _vels(plan) == [80, 90, 100]
    assert plan["changed_notes"] == 0


def test_full_compression_pulls_to_the_mean():
    plan = build_velocity_groove_plan(_clip([60, 80, 100]), dynamics=-1.0)
    assert _vels(plan) == [80, 80, 80]  # mean is 80


def test_expansion_widens_the_range():
    plan = build_velocity_groove_plan(_clip([60, 80, 100]), dynamics=1.0)
    # deviation doubled about the mean 80: 40, 80, 120
    assert _vels(plan) == [40, 80, 120]


def test_crescendo_ramps_up_over_time():
    # Four equal notes at t=0,1,2,3 in a 4-beat clip: velocities rise across the clip.
    plan = build_velocity_groove_plan(_clip([100, 100, 100, 100]), crescendo=1.0)
    vels = _vels(plan)
    assert vels == sorted(vels)  # non-decreasing
    assert vels[0] < 100 < vels[-1]  # first below, last above


def test_decrescendo_ramps_down():
    plan = build_velocity_groove_plan(_clip([100, 100, 100, 100]), crescendo=-1.0)
    vels = _vels(plan)
    assert vels == sorted(vels, reverse=True)
    assert vels[0] > vels[-1]


def test_accent_pattern_cycles_over_grid():
    # Grid 1 beat, pattern boosts every other step.
    plan = build_velocity_groove_plan(
        _clip([80, 80, 80, 80]), accent_pattern=[1.25, 0.75], grid_beats=1.0
    )
    assert _vels(plan) == [100, 60, 100, 60]


def test_velocity_clamped_to_1_127():
    plan = build_velocity_groove_plan(_clip([120, 10]), accent_pattern=[2.0, 0.01], grid_beats=1.0)
    vels = _vels(plan)
    assert vels[0] == 127  # 120*2 clamped
    assert vels[1] == 1  # 10*0.01 rounds to 0 -> clamped up to 1


def test_only_velocity_changes():
    clip = _clip([80])
    clip["notes"][0]["probability"] = 0.6
    plan = build_velocity_groove_plan(clip, dynamics=1.0)
    note = plan["notes"][0]
    assert note["pitch"] == 60
    assert note["start_time"] == 0.0
    assert note["duration"] == 0.5
    assert note["probability"] == 0.6


def test_reports_ranges_and_changes():
    plan = build_velocity_groove_plan(_clip([60, 80, 100]), dynamics=1.0)
    assert plan["source_velocity_range"] == {"min": 60, "max": 100}
    assert plan["result_velocity_range"] == {"min": 40, "max": 120}
    assert plan["changed_notes"] == 2  # the mean note is unchanged
    assert plan["max_velocity_delta"] == 20


def test_fingerprint_is_source_based():
    clip = _clip([80, 90])
    a = build_velocity_groove_plan(clip, dynamics=0.5)["source_fingerprint"]
    b = build_velocity_groove_plan(clip, crescendo=0.5)["source_fingerprint"]
    assert a == b


def test_bad_parameters_rejected():
    with pytest.raises(ValueError):
        build_velocity_groove_plan(_clip([80]), crescendo=2.0)
    with pytest.raises(ValueError):
        build_velocity_groove_plan(_clip([80]), dynamics=-1.5)
    with pytest.raises(ValueError):
        build_velocity_groove_plan(_clip([80]), accent_pattern=[1.0, -0.5])
    with pytest.raises(ValueError):
        build_velocity_groove_plan(_clip([80]), accent_pattern=[1.0], grid_beats=0.0)
    with pytest.raises(ValueError):
        build_velocity_groove_plan({"length_beats": 4.0, "notes": []})
