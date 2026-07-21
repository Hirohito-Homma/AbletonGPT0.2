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


# --- musical parameters: --tempo -------------------------------------------------

def _tempo_steps(plan) -> list:
    return [step for step in plan.steps if step.command == "set_tempo"]


def test_tempo_adds_set_tempo_step_to_job_plan(tmp_path: Path):
    out = tmp_path / "plan.json"
    executor = FakeExecutor()

    rc = main(
        ["arrange-run", "--job-path", str(out), "--tempo", "126"],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    plan = load_job_plan(out)
    tempo_steps = _tempo_steps(plan)
    assert len(tempo_steps) == 1
    assert tempo_steps[0].params["bpm"] == 126
    # The tempo step runs first, before any scene is placed.
    assert plan.steps[0].command == "set_tempo"
    assert executor.executed[0] == tempo_steps[0].step_id


def test_dry_run_tempo_is_reported_and_not_executed(tmp_path: Path, capsys):
    executor = FakeExecutor()

    rc = main(
        ["arrange-run", "--dry-run", "--tempo", "126"],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    assert executor.executed == []
    assert "tempo=126" in capsys.readouterr().out


# --- musical parameters: --bars --------------------------------------------------

def test_bars_scales_total_arrangement_length(tmp_path: Path):
    out = tmp_path / "plan.json"

    rc = main(
        ["arrange-run", "--job-path", str(out), "--bars", "64"],
        executor_factory=_factory(FakeExecutor()),
    )

    assert rc == 0
    plan = load_job_plan(out)
    total = sum(
        step.params["length_bars"]
        for step in plan.steps
        if step.command == "place_scene"
    )
    assert total == 64
    # Sections stay contiguous and 1-based after rescaling.
    scene_steps = [s for s in plan.steps if s.command == "place_scene"]
    assert scene_steps[0].params["start_bar"] == 1
    bars_seen = [
        (s.params["start_bar"], s.params["length_bars"]) for s in scene_steps
    ]
    for (start, length), (next_start, _) in zip(bars_seen, bars_seen[1:]):
        assert start + length == next_start


def test_dry_run_bars_is_reported(capsys):
    rc = main(
        ["arrange-run", "--dry-run", "--bars", "64"],
        executor_factory=_factory(FakeExecutor()),
    )

    assert rc == 0
    assert "64 bar" in capsys.readouterr().out


# --- musical parameters: --name --------------------------------------------------

def test_name_is_reflected_in_job_plan(tmp_path: Path, capsys):
    out = tmp_path / "plan.json"

    rc = main(
        ["arrange-run", "--dry-run", "--name", "test_song"],
        executor_factory=_factory(FakeExecutor()),
    )
    assert rc == 0
    assert "test_song" in capsys.readouterr().out

    # And it lands on the persisted plan too.
    rc2 = main(
        ["arrange-run", "--job-path", str(out), "--name", "test_song"],
        executor_factory=_factory(FakeExecutor()),
    )
    assert rc2 == 0
    assert load_job_plan(out).name == "test_song"


# --- resume precedence over new parameters ---------------------------------------

def test_resume_ignores_new_tempo_and_bars(tmp_path: Path):
    out = tmp_path / "plan.json"
    # Seed an existing plan generated at tempo 120 / 56 bars.
    seed = build_job_plan(simple_arrangement("seeded", tempo=120))
    save_job_plan(seed, out)

    executor = FakeExecutor()
    rc = main(
        [
            "arrange-run",
            "--job-path",
            str(out),
            "--resume",
            "--tempo",
            "130",
            "--bars",
            "999",
            "--name",
            "regenerated",
        ],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    plan = load_job_plan(out)
    # The on-disk plan won: name, tempo, and length are all unchanged.
    assert plan.name == "seeded"
    tempo_steps = _tempo_steps(plan)
    assert len(tempo_steps) == 1
    assert tempo_steps[0].params["bpm"] == 120
    assert plan.step_ids == seed.step_ids


# --- style selection: --style ----------------------------------------------------

def test_default_style_matches_dark_tech_house(tmp_path: Path):
    # No --style: the default must produce exactly the built-in dark-tech-house plan.
    default_out = tmp_path / "default.json"
    styled_out = tmp_path / "styled.json"

    rc_default = main(
        ["arrange-run", "--job-path", str(default_out)],
        executor_factory=_factory(FakeExecutor()),
    )
    rc_styled = main(
        ["arrange-run", "--job-path", str(styled_out), "--style", "dark-tech-house"],
        executor_factory=_factory(FakeExecutor()),
    )

    assert rc_default == 0 and rc_styled == 0
    assert load_job_plan(default_out).step_ids == _DEFAULT_STEP_IDS
    # Explicit style == default: identical plans.
    assert load_job_plan(styled_out).step_ids == _DEFAULT_STEP_IDS


def test_style_dark_tech_house_runs(capsys):
    executor = FakeExecutor()

    rc = main(
        ["arrange-run", "--style", "dark-tech-house"],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    assert executor.executed == list(_DEFAULT_STEP_IDS)
    assert "failed=0" in capsys.readouterr().out


def test_unknown_style_fails_clearly(capsys):
    executor = FakeExecutor()

    rc = main(
        ["arrange-run", "--style", "unknown", "--dry-run"],
        executor_factory=_factory(executor),
    )

    # Non-zero exit, nothing executed, and a message that names the bad style plus
    # the styles that are actually available.
    assert rc != 0
    assert executor.executed == []
    err = capsys.readouterr().err
    assert "unsupported style" in err
    assert "'unknown'" in err
    assert "dark-tech-house" in err


def test_style_combines_with_tempo_bars_name(tmp_path: Path, capsys):
    rc = main(
        [
            "arrange-run",
            "--style",
            "dark-tech-house",
            "--tempo",
            "126",
            "--bars",
            "64",
            "--name",
            "styled_song",
            "--dry-run",
        ],
        executor_factory=_factory(FakeExecutor()),
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "styled_song" in out
    assert "tempo=126" in out
    assert "64 bar" in out


def test_resume_ignores_style(tmp_path: Path):
    out = tmp_path / "plan.json"
    # Seed a distinctive existing plan.
    seed = build_job_plan(simple_arrangement("seeded", tempo=120))
    save_job_plan(seed, out)

    # An unknown style would fail on a fresh build, but resume must not regenerate:
    # it reloads the saved plan and ignores --style entirely.
    executor = FakeExecutor()
    rc = main(
        ["arrange-run", "--job-path", str(out), "--resume", "--style", "unknown"],
        executor_factory=_factory(executor),
    )

    assert rc == 0
    assert load_job_plan(out).step_ids == seed.step_ids
