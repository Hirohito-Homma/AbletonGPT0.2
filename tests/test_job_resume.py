from __future__ import annotations

from pathlib import Path

from abletongpt.arrange import ArrangeEngine
from abletongpt.jobs import (
    JobPlan,
    JobStep,
    StepStatus,
    build_job_plan,
    completed_step_ids,
    load_step_statuses,
    run_saved_job_plan,
    save_job_plan,
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


def _executed_ids(executor: RecordingExecutor) -> list[str]:
    return [step.step_id for step in executor.executed]


# --- completed_step_ids helper ----------------------------------------------------

def test_completed_step_ids_selects_only_finished_statuses():
    statuses = {
        "a": StepStatus.SUCCEEDED,
        "b": StepStatus.SKIPPED,
        "c": StepStatus.PENDING,
        "d": StepStatus.FAILED,
    }
    assert set(completed_step_ids(statuses)) == {"a", "b"}


# --- fresh run --------------------------------------------------------------------

def test_fresh_plan_runs_every_step_and_saves_success(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "plan.json"
    save_job_plan(plan, path)  # all steps default to PENDING

    executor = RecordingExecutor()
    result = run_saved_job_plan(path, executor)

    assert result.succeeded
    assert _executed_ids(executor) == list(plan.step_ids)
    saved = load_step_statuses(path)
    assert all(status is StepStatus.SUCCEEDED for status in saved.values())


# --- completed steps are skipped --------------------------------------------------

def test_completed_steps_are_not_re_run_and_stay_recorded(tmp_path: Path):
    plan = _default_job_plan()
    ids = plan.step_ids
    path = tmp_path / "plan.json"
    save_job_plan(
        plan,
        path,
        statuses={ids[0]: StepStatus.SUCCEEDED, ids[1]: StepStatus.SUCCEEDED},
    )

    executor = RecordingExecutor()
    result = run_saved_job_plan(path, executor)

    assert result.succeeded
    # Only the not-yet-completed steps were handed to the executor.
    assert _executed_ids(executor) == list(ids[2:])

    saved = load_step_statuses(path)
    # Previously completed steps keep SUCCEEDED (not demoted to SKIPPED)...
    assert saved[ids[0]] is StepStatus.SUCCEEDED
    assert saved[ids[1]] is StepStatus.SUCCEEDED
    # ...and the freshly run ones are recorded as SUCCEEDED too.
    assert all(saved[step_id] is StepStatus.SUCCEEDED for step_id in ids[2:])


# --- failed steps are re-run ------------------------------------------------------

def test_failed_step_is_re_run_on_resume(tmp_path: Path):
    plan = _default_job_plan()
    ids = plan.step_ids
    path = tmp_path / "plan.json"
    # Steps 0-1 done, step 2 previously FAILED, the rest still PENDING.
    save_job_plan(
        plan,
        path,
        statuses={
            ids[0]: StepStatus.SUCCEEDED,
            ids[1]: StepStatus.SUCCEEDED,
            ids[2]: StepStatus.FAILED,
        },
    )

    executor = RecordingExecutor()
    result = run_saved_job_plan(path, executor)

    assert result.succeeded
    # The failed step and everything after it run; the two done steps do not.
    assert _executed_ids(executor) == list(ids[2:])
    saved = load_step_statuses(path)
    assert saved[ids[2]] is StepStatus.SUCCEEDED


# --- retry honors max_attempts ----------------------------------------------------

def test_retry_recovers_transient_failure_via_max_attempts(tmp_path: Path):
    plan = _default_job_plan()
    target = plan.step_ids[2]
    path = tmp_path / "plan.json"
    save_job_plan(plan, path)

    executor = FlakyExecutor(fail_ids={target}, fail_times=1)
    result = run_saved_job_plan(path, executor, max_attempts=3)

    assert result.succeeded
    target_result = next(r for r in result.results if r.step_id == target)
    assert target_result.status is StepStatus.SUCCEEDED
    assert target_result.attempts == 2
    assert load_step_statuses(path)[target] is StepStatus.SUCCEEDED


# --- halt then resume across two saved runs ---------------------------------------

def test_permanent_failure_persists_progress_then_resumes_cleanly(tmp_path: Path):
    plan = _default_job_plan()
    ids = plan.step_ids
    target = ids[2]
    path = tmp_path / "plan.json"
    save_job_plan(plan, path)

    # First run: step 2 always fails, halting the run.
    first = run_saved_job_plan(
        path, FlakyExecutor(fail_ids={target}, fail_times=99), max_attempts=1
    )
    assert not first.succeeded

    saved = load_step_statuses(path)
    assert all(saved[step_id] is StepStatus.SUCCEEDED for step_id in ids[:2])
    assert saved[target] is StepStatus.FAILED
    assert all(saved[step_id] is StepStatus.PENDING for step_id in ids[3:])

    # Second run with a healthy executor resumes from the failed step onward.
    executor = RecordingExecutor()
    second = run_saved_job_plan(path, executor)

    assert second.succeeded
    assert _executed_ids(executor) == list(ids[2:])
    assert all(
        status is StepStatus.SUCCEEDED for status in load_step_statuses(path).values()
    )


# --- dry run ----------------------------------------------------------------------

def test_save_back_false_leaves_file_untouched(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "plan.json"
    save_job_plan(plan, path)
    before = path.read_text(encoding="utf-8")

    result = run_saved_job_plan(path, RecordingExecutor(), save_back=False)

    assert result.succeeded
    assert path.read_text(encoding="utf-8") == before
    assert all(
        status is StepStatus.PENDING for status in load_step_statuses(path).values()
    )
