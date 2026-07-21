from __future__ import annotations

import json
from pathlib import Path

import pytest

from abletongpt.cli.jobs import main
from abletongpt.jobs import (
    JobPlan,
    JobStep,
    StepStatus,
    load_job_plan,
    load_step_statuses,
    save_job_plan,
)


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


_ARRANGEMENT = {
    "name": "test_song",
    "sections": [
        {
            "section_id": "s0",
            "name": "Intro",
            "source_scene": "intro",
            "start_bar": 0,
            "length_bars": 8,
        },
        {
            "section_id": "s1",
            "name": "Drop",
            "source_scene": "drop",
            "start_bar": 8,
            "length_bars": 16,
        },
    ],
}


def _write_arrangement(path: Path) -> Path:
    path.write_text(json.dumps(_ARRANGEMENT), encoding="utf-8")
    return path


def _sample_plan() -> JobPlan:
    return JobPlan(
        name="p",
        steps=(
            JobStep("00_a", "play"),
            JobStep("01_b", "stop"),
            JobStep("02_c", "get_tracks"),
        ),
    )


# --- create ----------------------------------------------------------------------

def test_create_builds_job_plan_json_from_arrangement(tmp_path: Path, capsys):
    arrangement = _write_arrangement(tmp_path / "arr.json")
    out = tmp_path / "plan.json"

    rc = main(["create", "--arrangement", str(arrangement), "--out", str(out)])

    assert rc == 0
    assert out.exists()
    plan = load_job_plan(out)
    assert plan.name == "test_song"
    assert plan.step_ids == ("00_place_scene_intro", "01_place_scene_drop")
    assert all(step.command == "place_scene" for step in plan.steps)
    # Fresh plan: every step starts pending.
    assert set(load_step_statuses(out).values()) == {StepStatus.PENDING}

    out_text = capsys.readouterr().out
    assert "2 step" in out_text


def test_create_makes_missing_parent_directories(tmp_path: Path):
    arrangement = _write_arrangement(tmp_path / "arr.json")
    out = tmp_path / "nested" / "deep" / "plan.json"

    rc = main(["create", "--arrangement", str(arrangement), "--out", str(out)])

    assert rc == 0
    assert out.exists()  # save_job_plan created nested/deep/
    assert load_job_plan(out).step_ids == ("00_place_scene_intro", "01_place_scene_drop")


# --- status ----------------------------------------------------------------------

def test_status_reports_counts_without_executing(tmp_path: Path, capsys):
    plan = _sample_plan()
    path = tmp_path / "plan.json"
    save_job_plan(
        plan,
        path,
        statuses={
            "00_a": StepStatus.SUCCEEDED,
            "01_b": StepStatus.FAILED,
            # 02_c omitted -> pending
        },
    )

    rc = main(["status", "--plan", str(path)])

    assert rc == 0
    assert "completed=1 failed=1 pending=1" in capsys.readouterr().out


def test_status_json_reports_counts(tmp_path: Path, capsys):
    plan = _sample_plan()
    path = tmp_path / "plan.json"
    save_job_plan(
        plan,
        path,
        statuses={
            "00_a": StepStatus.SUCCEEDED,
            "01_b": StepStatus.FAILED,
            # 02_c omitted -> pending
        },
    )

    rc = main(["status", "--plan", str(path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"completed": 1, "failed": 1, "pending": 1, "total": 3}


# --- run -------------------------------------------------------------------------

def test_run_executes_pending_steps_and_resaves_status(tmp_path: Path, capsys):
    plan = _sample_plan()
    path = tmp_path / "plan.json"
    save_job_plan(plan, path)  # all pending

    executor = FakeExecutor()
    rc = main(["run", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 0
    assert executor.executed == ["00_a", "01_b", "02_c"]
    # Progress was written back to the same file.
    assert set(load_step_statuses(path).values()) == {StepStatus.SUCCEEDED}
    assert "completed=3 failed=0 pending=0" in capsys.readouterr().out


# --- resume ----------------------------------------------------------------------

def test_resume_does_not_rerun_completed_steps(tmp_path: Path):
    plan = _sample_plan()
    path = tmp_path / "plan.json"
    # First step already done on disk.
    save_job_plan(plan, path, statuses={"00_a": StepStatus.SUCCEEDED})

    executor = FakeExecutor()
    rc = main(["resume", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 0
    # The completed step was skipped; only the rest ran.
    assert executor.executed == ["01_b", "02_c"]
    statuses = load_step_statuses(path)
    # Previously-completed step stays completed; the rest are now done too.
    assert statuses["00_a"] is StepStatus.SUCCEEDED
    assert statuses["01_b"] is StepStatus.SUCCEEDED
    assert statuses["02_c"] is StepStatus.SUCCEEDED


# --- failure exit codes ----------------------------------------------------------

def test_run_returns_exit_code_1_on_failure(tmp_path: Path):
    plan = _sample_plan()
    path = tmp_path / "plan.json"
    save_job_plan(plan, path)

    executor = FakeExecutor(fail_ids={"01_b"})
    rc = main(["run", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 1
    statuses = load_step_statuses(path)
    assert statuses["00_a"] is StepStatus.SUCCEEDED
    assert statuses["01_b"] is StepStatus.FAILED
    # stop_on_error halts the run; the trailing step stays pending on disk.
    assert statuses["02_c"] is StepStatus.PENDING


def test_resume_returns_exit_code_1_on_failure(tmp_path: Path):
    plan = _sample_plan()
    path = tmp_path / "plan.json"
    save_job_plan(plan, path, statuses={"00_a": StepStatus.SUCCEEDED})

    executor = FakeExecutor(fail_ids={"01_b"})
    rc = main(["resume", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 1
    # The already-completed step was not re-run.
    assert executor.executed == ["01_b"]
    assert load_step_statuses(path)["01_b"] is StepStatus.FAILED


# --- parser ----------------------------------------------------------------------

def test_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main([])
