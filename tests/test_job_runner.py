from __future__ import annotations

import pytest

from abletongpt.arrange import ArrangeEngine, ArrangementPlan
from abletongpt.jobs import (
    JobPlan,
    JobRunner,
    JobStep,
    StepStatus,
    build_job_plan,
)


class RecordingExecutor:
    """Fake executor: records the steps it runs. No Live involved."""

    def __init__(self):
        self.executed: list[JobStep] = []

    def execute(self, step: JobStep) -> None:
        self.executed.append(step)


class FlakyExecutor:
    """Fails ``fail_ids`` for the first ``fail_times`` attempts, then succeeds."""

    def __init__(self, fail_ids: set[str], fail_times: int):
        self._fail_ids = set(fail_ids)
        self._fail_times = fail_times
        self.attempts: dict[str, int] = {}

    def execute(self, step: JobStep) -> None:
        self.attempts[step.step_id] = self.attempts.get(step.step_id, 0) + 1
        if step.step_id in self._fail_ids and self.attempts[step.step_id] <= self._fail_times:
            raise RuntimeError("boom: %s" % step.step_id)


def _default_job_plan() -> JobPlan:
    return build_job_plan(ArrangeEngine().dark_tech_house_default())


# --- translation -----------------------------------------------------------------

def test_build_job_plan_maps_sections_in_order():
    arrangement = ArrangeEngine().dark_tech_house_default()
    plan = build_job_plan(arrangement)

    assert isinstance(plan, JobPlan)
    assert plan.name == "dark_tech_house_default"
    assert len(plan.steps) == len(arrangement.sections)

    for step, operation in zip(plan.steps, _operations(arrangement)):
        assert step.command == "place_scene"
        assert step.params["source_scene"] == operation.source_scene
        assert step.params["start_bar"] == operation.start_bar
        assert step.params["length_bars"] == operation.length_bars
        assert step.params["transition"] == operation.transition


def test_step_ids_are_unique_and_ordered():
    plan = _default_job_plan()
    ids = plan.step_ids
    assert len(set(ids)) == len(ids)
    assert ids[0] == "00_place_scene_intro"
    assert ids[-1] == "06_place_scene_outro"


def test_build_job_plan_is_deterministic():
    engine = ArrangeEngine()
    assert build_job_plan(engine.dark_tech_house_default()) == build_job_plan(
        engine.dark_tech_house_default()
    )


def test_empty_arrangement_yields_empty_job_plan():
    plan = build_job_plan(ArrangementPlan(name="empty"))
    assert plan.steps == ()
    assert plan.step_ids == ()


# --- running ---------------------------------------------------------------------

def test_runner_executes_every_step_in_order():
    plan = _default_job_plan()
    executor = RecordingExecutor()
    result = JobRunner(executor).run(plan)

    assert result.succeeded
    assert [s.step_id for s in executor.executed] == list(plan.step_ids)
    assert all(r.status is StepStatus.SUCCEEDED for r in result.results)
    assert all(r.attempts == 1 for r in result.results)


def test_empty_plan_run_succeeds_trivially():
    result = JobRunner(RecordingExecutor()).run(JobPlan(name="empty"))
    assert result.results == ()
    assert result.succeeded


# --- resume ----------------------------------------------------------------------

def test_resume_skips_completed_steps():
    plan = _default_job_plan()
    executor = RecordingExecutor()
    done = plan.step_ids[:3]

    result = JobRunner(executor).run(plan, completed_step_ids=done)

    # The first three are skipped and never handed to the executor.
    assert [s.step_id for s in executor.executed] == list(plan.step_ids[3:])
    for r in result.results[:3]:
        assert r.status is StepStatus.SKIPPED
    assert result.succeeded


# --- retry -----------------------------------------------------------------------

def test_retry_recovers_a_transient_failure():
    plan = _default_job_plan()
    target = plan.step_ids[2]
    executor = FlakyExecutor(fail_ids={target}, fail_times=1)

    result = JobRunner(executor).run(plan, max_attempts=3)

    assert result.succeeded
    target_result = next(r for r in result.results if r.step_id == target)
    assert target_result.status is StepStatus.SUCCEEDED
    assert target_result.attempts == 2


def test_permanent_failure_halts_and_leaves_rest_pending():
    plan = _default_job_plan()
    target = plan.step_ids[2]
    executor = FlakyExecutor(fail_ids={target}, fail_times=99)

    result = JobRunner(executor).run(plan, max_attempts=2)

    assert not result.succeeded
    assert result.failed_step_ids == (target,)
    # Everything before the failure completed; everything after stays pending.
    assert result.completed_step_ids == plan.step_ids[:2]
    assert result.pending_step_ids == plan.step_ids[3:]

    failed = next(r for r in result.results if r.step_id == target)
    assert failed.attempts == 2
    assert failed.error is not None


def test_failed_run_is_resumable_from_its_own_result():
    plan = _default_job_plan()
    target = plan.step_ids[2]

    first = JobRunner(FlakyExecutor(fail_ids={target}, fail_times=99)).run(plan)
    assert not first.succeeded

    # Second attempt with a healthy executor, resuming from what already completed.
    executor = RecordingExecutor()
    second = JobRunner(executor).run(plan, completed_step_ids=first.completed_step_ids)

    assert second.succeeded
    # Only the not-yet-completed steps are re-run.
    assert [s.step_id for s in executor.executed] == list(plan.step_ids[2:])


def test_max_attempts_must_be_positive():
    with pytest.raises(ValueError):
        JobRunner(RecordingExecutor()).run(_default_job_plan(), max_attempts=0)


# --- helpers ---------------------------------------------------------------------

def _operations(arrangement):
    from abletongpt.arrange import build_operations

    return build_operations(arrangement)
