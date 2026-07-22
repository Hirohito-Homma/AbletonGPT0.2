from __future__ import annotations

from pathlib import Path

from abletongpt.arrange import ArrangeEngine
from abletongpt.jobs import (
    JobPlan,
    JobRunner,
    JobStep,
    StepStatus,
    build_job_plan,
    load_job_plan,
    load_step_statuses,
)


class RecordingExecutor:
    """Fake executor: records the steps it runs. No Live involved."""

    def __init__(self) -> None:
        self.executed: list[JobStep] = []

    def execute(self, step: JobStep) -> None:
        self.executed.append(step)


class FlakyExecutor:
    """Fails ``fail_ids`` for the first ``fail_times`` attempts, then succeeds."""

    def __init__(self, fail_ids: set[str], fail_times: int) -> None:
        self._fail_ids = set(fail_ids)
        self._fail_times = fail_times
        self.attempts: dict[str, int] = {}

    def execute(self, step: JobStep) -> None:
        self.attempts[step.step_id] = self.attempts.get(step.step_id, 0) + 1
        if (
            step.step_id in self._fail_ids
            and self.attempts[step.step_id] <= self._fail_times
        ):
            raise RuntimeError("boom: %s" % step.step_id)


def _default_job_plan() -> JobPlan:
    return build_job_plan(ArrangeEngine().dark_tech_house_default())


# --- no persistence: unchanged behavior ------------------------------------------

def test_run_without_persistence_path_behaves_as_before(tmp_path: Path):
    plan = _default_job_plan()
    executor = RecordingExecutor()

    result = JobRunner(executor).run(plan)  # no persistence_path

    assert result.succeeded
    assert [s.step_id for s in executor.executed] == list(plan.step_ids)
    # Nothing was written to disk.
    assert list(tmp_path.iterdir()) == []


# --- persistence writes progress -------------------------------------------------

def test_plan_is_saved_after_a_step_completes(tmp_path: Path):
    plan = JobPlan(
        name="single",
        steps=(JobStep("00_only", "place_scene", {"source_scene": "intro"}),),
    )
    path = tmp_path / "progress.json"

    JobRunner(RecordingExecutor()).run(plan, persistence_path=path)

    assert path.exists()
    # The saved plan round-trips and the step's success is recorded.
    assert load_job_plan(path) == plan
    assert load_step_statuses(path) == {"00_only": StepStatus.SUCCEEDED}


def test_multi_step_statuses_are_reflected_in_the_saved_file(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "multi.json"

    JobRunner(RecordingExecutor()).run(plan, persistence_path=path)

    assert load_job_plan(path) == plan
    statuses = load_step_statuses(path)
    # Every step ran and succeeded.
    assert set(statuses) == set(plan.step_ids)
    assert all(status is StepStatus.SUCCEEDED for status in statuses.values())


def test_failed_step_status_is_persisted(tmp_path: Path):
    plan = _default_job_plan()
    target = plan.step_ids[2]
    path = tmp_path / "failed.json"

    result = JobRunner(FlakyExecutor(fail_ids={target}, fail_times=99)).run(
        plan, persistence_path=path
    )
    assert not result.succeeded

    statuses = load_step_statuses(path)
    # Steps before the failure succeeded, the target failed, the rest stay pending.
    assert statuses[target] is StepStatus.FAILED
    for step_id in plan.step_ids[:2]:
        assert statuses[step_id] is StepStatus.SUCCEEDED
    for step_id in plan.step_ids[3:]:
        assert statuses[step_id] is StepStatus.PENDING


# --- resume from a saved plan ----------------------------------------------------

def test_completed_steps_are_skipped_when_resuming_from_a_saved_plan(tmp_path: Path):
    plan = _default_job_plan()
    target = plan.step_ids[2]
    path = tmp_path / "resume.json"

    # First run halts on a permanent failure and persists its progress.
    first = JobRunner(FlakyExecutor(fail_ids={target}, fail_times=99)).run(
        plan, persistence_path=path
    )
    assert not first.succeeded

    # Reconstruct the plan and the completed ids purely from disk.
    loaded_plan = load_job_plan(path)
    saved_statuses = load_step_statuses(path)
    completed = tuple(
        step_id
        for step_id, status in saved_statuses.items()
        if status is StepStatus.SUCCEEDED
    )

    executor = RecordingExecutor()
    second = JobRunner(executor).run(loaded_plan, completed_step_ids=completed)

    # The already-completed steps are skipped; only the rest are re-run.
    for step_id in completed:
        skipped = next(r for r in second.results if r.step_id == step_id)
        assert skipped.status is StepStatus.SKIPPED
    assert list(completed) == list(plan.step_ids[:2])
    assert [s.step_id for s in executor.executed] == list(plan.step_ids[2:])
    assert second.succeeded


def test_failed_step_is_retried_and_the_saved_file_is_updated(tmp_path: Path):
    plan = _default_job_plan()
    target = plan.step_ids[2]
    path = tmp_path / "retry.json"

    # First run: the target fails permanently and is persisted as FAILED.
    JobRunner(FlakyExecutor(fail_ids={target}, fail_times=99)).run(
        plan, persistence_path=path
    )
    assert load_step_statuses(path)[target] is StepStatus.FAILED

    # Retry with a healthy executor, writing to the same file.
    result = JobRunner(RecordingExecutor()).run(plan, persistence_path=path)

    assert result.succeeded
    updated = load_step_statuses(path)
    # The previously-failed step is now recorded as succeeded on disk.
    assert updated[target] is StepStatus.SUCCEEDED
    assert all(status is StepStatus.SUCCEEDED for status in updated.values())
