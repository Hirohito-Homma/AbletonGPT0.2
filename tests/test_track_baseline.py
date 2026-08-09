from __future__ import annotations

from typing import Any

import pytest

from abletongpt.jobs import (
    JobPlan,
    JobStep,
    TrackBaselineMismatch,
    build_track_expectation,
    verify_track_baseline,
)


def _plan(*steps: JobStep) -> JobPlan:
    return JobPlan(name="P", steps=tuple(steps))


def _create(step_id: str, index: int = -1) -> JobStep:
    return JobStep(step_id, "create_track", {"track_type": "midi", "index": index})


def _clip(step_id: str, track_index: int) -> JobStep:
    return JobStep(
        step_id,
        "create_midi_clip",
        {
            "track_index": track_index,
            "clip_index": 0,
            "name": "c",
            "length_beats": 4.0,
            "notes": [],
        },
    )


class _Bridge:
    def __init__(self, track_count: int) -> None:
        self.state = {"tracks": [{"index": i} for i in range(track_count)]}
        self.calls: list[str] = []

    def call(self, command: str, **params: Any) -> Any:
        self.calls.append(command)
        if command == "get_state":
            return self.state
        raise AssertionError("the guard must only read state, got: %s" % command)


# --- expectation ---------------------------------------------------------------

def test_base_index_is_the_lowest_targeted_track():
    plan = _plan(_create("a"), _create("b"), _clip("c", 5), _clip("d", 3), _clip("e", 4))

    expectation = build_track_expectation(plan)

    assert expectation.base_index == 3
    assert expectation.creates == 2
    assert expectation.creates_done == 0
    assert expectation.expected_track_count == 3


def test_resume_counts_the_tracks_already_created():
    plan = _plan(_create("a"), _create("b"), _clip("c", 3))

    expectation = build_track_expectation(plan, completed_step_ids=["a"])

    assert expectation.creates_done == 1
    # one track already exists, so the Set should now hold base + 1
    assert expectation.expected_track_count == 4


def test_a_plan_targeting_no_track_has_no_opinion():
    plan = _plan(JobStep("t", "set_tempo", {"bpm": 120}))

    assert build_track_expectation(plan) is None


def test_an_explicitly_inserted_track_makes_the_plan_uncheckable():
    # Insert position depends on order, not on the track count, so the arithmetic
    # here would be wrong -- and a wrong guard is worse than none.
    plan = _plan(_create("a", index=0), _clip("b", 0))

    assert build_track_expectation(plan) is None


def test_a_bool_track_index_is_not_treated_as_a_number():
    plan = _plan(_create("a"), JobStep("b", "create_midi_clip", {"track_index": True}))

    assert build_track_expectation(plan) is None


# --- verification --------------------------------------------------------------

def test_a_matching_set_passes_and_only_reads():
    plan = _plan(_create("a"), _clip("b", 3))
    bridge = _Bridge(3)

    assert verify_track_baseline(bridge, build_track_expectation(plan)) == 3
    assert bridge.calls == ["get_state"]


def test_a_set_with_extra_tracks_is_refused_before_anything_runs():
    plan = _plan(_create("a"), _clip("b", 0))
    bridge = _Bridge(3)

    with pytest.raises(TrackBaselineMismatch) as exc:
        verify_track_baseline(bridge, build_track_expectation(plan))

    message = str(exc.value)
    assert "Live has 3 track(s)" in message
    # the fix has to be actionable, not just a complaint
    assert "--first-track-index 3" in message


def test_a_set_with_too_few_tracks_is_also_refused():
    plan = _plan(_create("a"), _clip("b", 5))
    bridge = _Bridge(2)

    with pytest.raises(TrackBaselineMismatch, match="--first-track-index 2"):
        verify_track_baseline(bridge, build_track_expectation(plan))


def test_resume_into_a_changed_set_is_refused_with_resume_specific_advice():
    plan = _plan(_create("a"), _create("b"), _clip("c", 3))
    bridge = _Bridge(9)

    with pytest.raises(TrackBaselineMismatch) as exc:
        verify_track_baseline(
            bridge, build_track_expectation(plan, completed_step_ids=["a"])
        )

    message = str(exc.value)
    assert "re-import" in message
    # resuming is not fixed by rebuilding with a new offset, so it must not say that
    assert "--first-track-index" not in message


def test_resume_that_still_lines_up_passes():
    plan = _plan(_create("a"), _create("b"), _clip("c", 3))
    bridge = _Bridge(4)

    expectation = build_track_expectation(plan, completed_step_ids=["a"])

    assert verify_track_baseline(bridge, expectation) == 4


def test_a_malformed_state_is_refused_rather_than_assumed_safe():
    plan = _plan(_create("a"), _clip("b", 0))

    class _Broken:
        def call(self, command, **params):
            return {"tracks": "not a list"}

    with pytest.raises(TrackBaselineMismatch, match="did not report a track list"):
        verify_track_baseline(_Broken(), build_track_expectation(plan))
