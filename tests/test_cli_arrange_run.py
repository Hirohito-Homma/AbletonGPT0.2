"""Tests for the ``arrange-run`` one-shot CLI command.

``arrange-run`` chains the existing engines end-to-end: generate the default
arrangement -> build a job plan -> optionally save -> run via an executor. Every test
here injects a fake executor, so nothing ever touches Ableton or a socket.
"""

from __future__ import annotations

from pathlib import Path

from abletongpt.cli.jobs import main
from abletongpt.jobs import (
    JobStep,
    StepStatus,
    build_job_plan,
    load_job_plan,
    load_step_statuses,
    save_job_plan,
)
from abletongpt.arrange.presets import simple_arrangement


class FakeExecutor:
    """Records executed step ids; optionally fails a chosen set. No Ableton/socket."""

    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.executed: list[str] = []

    def execute(self, step: JobStep) -> None:
        self.executed.append(step.step_id)
        if step.step_id in self.fail_ids:
            raise RuntimeError("boom: %s" % step.step_id)


def _factory(executor: FakeExecutor):
    """Executor factory that always returns the same fake, so tests can inspect it."""
    return lambda: executor


# The step ids arrange-run generates for the default arrangement, in order.
_DEFAULT_STEP_IDS = tuple(build_job_plan(simple_arrangement()).step_ids)


# --- dry-run ---------------------------------------------------------------------

def test_dry_run_builds_plan_without_executing_or_saving(tmp_path: Path, capsys):
    out = tmp_path / "plan.json"
    executor = FakeExecutor()

    rc = main(
        ["arrange-run", "--job-path", str(out), "--dry-run"],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    # Nothing ran and nothing was written.
    assert executor.executed == []
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "dry-run" in printed
    # The summary reflects the real generated plan (5 default sections/steps).
    assert "%d step" % len(_DEFAULT_STEP_IDS) in printed


# --- execution -------------------------------------------------------------------

def test_arrange_run_executes_generated_plan(tmp_path: Path, capsys):
    executor = FakeExecutor()

    rc = main(["arrange-run"], executor_factory=_factory(executor))

    assert rc == 0
    # Every step of the default arrangement was handed to the executor, in order.
    assert executor.executed == list(_DEFAULT_STEP_IDS)
    assert "failed=0" in capsys.readouterr().out


# --- saving ----------------------------------------------------------------------

def test_arrange_run_saves_plan_when_job_path_given(tmp_path: Path):
    out = tmp_path / "nested" / "plan.json"
    executor = FakeExecutor()

    rc = main(
        ["arrange-run", "--job-path", str(out)],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    assert out.exists()  # save_job_plan created nested/ too
    saved = load_job_plan(out)
    assert saved.step_ids == _DEFAULT_STEP_IDS
    # Progress was persisted: a clean run leaves every step succeeded.
    assert set(load_step_statuses(out).values()) == {StepStatus.SUCCEEDED}


def test_arrange_run_no_save_skips_persistence(tmp_path: Path):
    out = tmp_path / "plan.json"
    executor = FakeExecutor()

    rc = main(
        ["arrange-run", "--job-path", str(out), "--no-save"],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    assert executor.executed == list(_DEFAULT_STEP_IDS)  # still ran
    assert not out.exists()  # but nothing written


# --- resume ----------------------------------------------------------------------

def test_resume_reloads_existing_plan_and_skips_completed(tmp_path: Path):
    out = tmp_path / "plan.json"
    # Seed an existing plan with its first step already completed on disk.
    plan = build_job_plan(simple_arrangement())
    first, *rest = plan.step_ids
    save_job_plan(plan, out, statuses={first: StepStatus.SUCCEEDED})

    executor = FakeExecutor()
    rc = main(
        ["arrange-run", "--job-path", str(out), "--resume"],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    # The completed step was skipped; only the remaining steps ran.
    assert executor.executed == rest
    statuses = load_step_statuses(out)
    assert statuses[first] is StepStatus.SUCCEEDED
    assert all(statuses[sid] is StepStatus.SUCCEEDED for sid in rest)


# --- failure exit code -----------------------------------------------------------

def test_arrange_run_returns_exit_code_1_on_failure(tmp_path: Path):
    out = tmp_path / "plan.json"
    # Fail the second generated step.
    doomed = _DEFAULT_STEP_IDS[1]
    executor = FakeExecutor(fail_ids={doomed})

    rc = main(
        ["arrange-run", "--job-path", str(out)],
        executor_factory=_factory(executor),
    )

    assert rc == 1
    statuses = load_step_statuses(out)
    assert statuses[_DEFAULT_STEP_IDS[0]] is StepStatus.SUCCEEDED
    assert statuses[doomed] is StepStatus.FAILED
    # stop_on_error halts the run; the trailing steps stay pending on disk.
    assert all(
        statuses[sid] is StepStatus.PENDING for sid in _DEFAULT_STEP_IDS[2:]
    )
