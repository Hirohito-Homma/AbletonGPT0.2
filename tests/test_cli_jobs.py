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


class SimulatedProcessExit(BaseException):
    """Models termination that JobRunner deliberately cannot catch."""


class InterruptingExecutor(FakeExecutor):
    def execute(self, step: JobStep) -> None:
        self.executed.append(step.step_id)
        if len(self.executed) == 2:
            raise SimulatedProcessExit("process stopped")


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


def _write_kihachi_plan(path: Path, *, operation="set_tempo") -> Path:
    params = (
        {"bpm": 110}
        if operation == "set_tempo"
        else {"file_path": "/tmp/take.wav"}
    )
    document = {
        "arrangement_plan_version": "0.1",
        "execution_state": "planned_not_applied",
        "song": {"title": "KIHACHI CLI"},
        "operations": [{"op": operation, "params": params}],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


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


def test_create_json_reports_written_plan(tmp_path: Path, capsys):
    arrangement = _write_arrangement(tmp_path / "arr.json")
    out = tmp_path / "plan.json"

    rc = main(["create", "--arrangement", str(arrangement), "--out", str(out), "--json"])

    assert rc == 0
    assert out.exists()  # the plan file is still written
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "test_song"
    assert payload["path"] == str(out)
    assert payload["step_count"] == len(load_job_plan(out).steps) == 2


def test_create_makes_missing_parent_directories(tmp_path: Path):
    arrangement = _write_arrangement(tmp_path / "arr.json")
    out = tmp_path / "nested" / "deep" / "plan.json"

    rc = main(["create", "--arrangement", str(arrangement), "--out", str(out)])

    assert rc == 0
    assert out.exists()  # save_job_plan created nested/deep/
    assert load_job_plan(out).step_ids == ("00_place_scene_intro", "01_place_scene_drop")


# --- import-kihachi --------------------------------------------------------------

def test_import_kihachi_writes_a_pending_job_without_executing(tmp_path: Path, capsys):
    source = _write_kihachi_plan(tmp_path / "arrangement_plan.json")
    out = tmp_path / "kihachi-job.json"
    executor = FakeExecutor()

    rc = main(
        [
            "import-kihachi",
            "--arrangement-plan",
            str(source),
            "--out",
            str(out),
        ],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    assert executor.executed == []
    assert load_job_plan(out).step_ids == ("0000_set_tempo",)
    assert set(load_step_statuses(out).values()) == {StepStatus.PENDING}
    assert "imported KIHACHI plan" in capsys.readouterr().out


def test_import_kihachi_rejects_non_core_plan_without_writing(tmp_path: Path, capsys):
    source = _write_kihachi_plan(
        tmp_path / "arrangement_plan.json", operation="import_vocal_take"
    )
    out = tmp_path / "kihachi-job.json"

    rc = main(
        [
            "import-kihachi",
            "--arrangement-plan",
            str(source),
            "--out",
            str(out),
        ]
    )

    assert rc == 2
    assert not out.exists()
    assert "import_vocal_take" in capsys.readouterr().err


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


def test_run_persists_each_completed_step_before_a_process_exit(tmp_path: Path):
    path = tmp_path / "plan.json"
    save_job_plan(_sample_plan(), path)

    with pytest.raises(SimulatedProcessExit):
        main(
            ["run", "--plan", str(path)],
            executor_factory=_factory(InterruptingExecutor()),
        )

    statuses = load_step_statuses(path)
    assert statuses["00_a"] is StepStatus.SUCCEEDED
    assert statuses["01_b"] is StepStatus.PENDING
    assert statuses["02_c"] is StepStatus.PENDING


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


# --- track baseline guard ---------------------------------------------------------

class BridgedExecutor(FakeExecutor):
    """A fake that also offers a bridge, so the preflight guard applies to it."""

    def __init__(self, track_count: int, fail_ids=()):
        super().__init__(fail_ids)
        self.bridge = _StateBridge(track_count)


class _StateBridge:
    def __init__(self, track_count: int) -> None:
        self._state = {"tracks": [{"index": i} for i in range(track_count)]}

    def call(self, command, **params):
        assert command == "get_state", "the guard must not mutate"
        return self._state


def _track_plan() -> JobPlan:
    """Two appended tracks, then a clip on the first of them (index 3)."""
    return JobPlan(
        name="tracks",
        steps=(
            JobStep("00_a", "create_track", {"track_type": "midi", "index": -1}),
            JobStep("01_b", "create_track", {"track_type": "midi", "index": -1}),
            JobStep(
                "02_c",
                "create_midi_clip",
                {
                    "track_index": 3,
                    "clip_index": 0,
                    "name": "c",
                    "length_beats": 4.0,
                    "notes": [],
                },
            ),
        ),
    )


def test_run_is_refused_without_executing_anything_when_the_set_does_not_match(
    tmp_path: Path, capsys
):
    path = tmp_path / "plan.json"
    save_job_plan(_track_plan(), path)

    executor = BridgedExecutor(track_count=5)  # plan was written for 3
    rc = main(["run", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 1
    # the whole point: nothing was touched
    assert executor.executed == []
    assert set(load_step_statuses(path).values()) == {StepStatus.PENDING}
    assert "--first-track-index 5" in capsys.readouterr().err


def test_run_proceeds_when_the_set_matches_the_plan(tmp_path: Path):
    path = tmp_path / "plan.json"
    save_job_plan(_track_plan(), path)

    executor = BridgedExecutor(track_count=3)
    rc = main(["run", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 0
    assert executor.executed == ["00_a", "01_b", "02_c"]


def test_an_executor_without_a_bridge_is_not_guarded(tmp_path: Path):
    """Existing fakes cannot be checked, and must keep working unchanged."""
    path = tmp_path / "plan.json"
    save_job_plan(_track_plan(), path)

    executor = FakeExecutor()
    rc = main(["run", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 0
    assert executor.executed == ["00_a", "01_b", "02_c"]


def test_resume_is_guarded_against_the_shifted_set(tmp_path: Path, capsys):
    path = tmp_path / "plan.json"
    save_job_plan(
        _track_plan(), path, statuses={"00_a": StepStatus.SUCCEEDED}
    )

    # one track was created, so a matching Set holds 4; this one drifted to 7
    executor = BridgedExecutor(track_count=7)
    rc = main(["resume", "--plan", str(path)], executor_factory=_factory(executor))

    assert rc == 1
    assert executor.executed == []
    assert "re-import" in capsys.readouterr().err
