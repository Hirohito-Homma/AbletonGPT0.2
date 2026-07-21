"""Command-line entry points for creating, running, and resuming job plans.

    python -m abletongpt.cli.jobs create --arrangement a.json --out plan.json
    python -m abletongpt.cli.jobs run     --plan plan.json
    python -m abletongpt.cli.jobs resume  --plan plan.json
    python -m abletongpt.cli.jobs status  --plan plan.json

The CLI is a thin wrapper over the existing pure engines and stores: it never talks
to Ableton itself, it hands each :class:`JobStep` to an executor. The executor is
supplied by ``executor_factory`` so tests can inject a fake and stay off the socket;
the default is :class:`~abletongpt.jobs.AbletonStepExecutor`.
"""

from __future__ import annotations

import argparse
from typing import Callable

from .serialization import arrangement_from_dict, read_json_document
from ..jobs import (
    AbletonStepExecutor,
    JobPlan,
    JobRunner,
    JobRunResult,
    StepExecutor,
    StepStatus,
    build_job_plan,
    load_job_plan,
    load_step_statuses,
    save_job_plan,
)

#: Zero-arg callable that yields a fresh executor. Overridable for tests.
ExecutorFactory = Callable[[], StepExecutor]

#: A step counts as "completed" (won't run again on resume) if it succeeded or was
#: already skipped, mirroring ``JobRunResult.completed_step_ids``.
_COMPLETED = (StepStatus.SUCCEEDED, StepStatus.SKIPPED)


def _default_executor_factory() -> StepExecutor:
    # AbletonBridge() reads config but does not connect until a step actually runs.
    return AbletonStepExecutor()


# --- progress accounting ---------------------------------------------------------

def _merge_statuses(
    prior: dict[str, StepStatus], result: JobRunResult
) -> dict[str, StepStatus]:
    """Fold a run's results over the previously-saved statuses.

    Keyed on the plan's steps (``result`` covers every step). A step the runner marked
    SKIPPED keeps whatever it already was on disk (e.g. SUCCEEDED from an earlier run),
    so resuming never downgrades completed work; every other step takes its fresh status.
    """
    final: dict[str, StepStatus] = {}
    for step_result in result.results:
        if step_result.status is StepStatus.SKIPPED and step_result.step_id in prior:
            final[step_result.step_id] = prior[step_result.step_id]
        else:
            final[step_result.step_id] = step_result.status
    return final


def _counts(statuses: dict[str, StepStatus]) -> tuple[int, int, int]:
    completed = sum(1 for status in statuses.values() if status in _COMPLETED)
    failed = sum(1 for status in statuses.values() if status is StepStatus.FAILED)
    pending = sum(1 for status in statuses.values() if status is StepStatus.PENDING)
    return completed, failed, pending


def _print_counts(statuses: dict[str, StepStatus]) -> tuple[int, int, int]:
    completed, failed, pending = _counts(statuses)
    print(
        "completed=%d failed=%d pending=%d" % (completed, failed, pending)
    )
    return completed, failed, pending


# --- subcommands -----------------------------------------------------------------

def _cmd_create(args: argparse.Namespace, _factory: ExecutorFactory) -> int:
    document = read_json_document(args.arrangement)
    arrangement = arrangement_from_dict(document)
    job_plan = build_job_plan(arrangement)
    out_path = save_job_plan(job_plan, args.out)  # creates parent dirs
    print(
        "created job plan '%s' with %d step(s) -> %s"
        % (job_plan.name, len(job_plan.steps), out_path)
    )
    return 0


def _execute(path: str, factory: ExecutorFactory, *, resume: bool) -> int:
    plan: JobPlan = load_job_plan(path)
    prior = load_step_statuses(path)
    completed_step_ids = (
        tuple(sid for sid, status in prior.items() if status in _COMPLETED)
        if resume
        else ()
    )

    result = JobRunner(factory()).run(plan, completed_step_ids=completed_step_ids)

    final = _merge_statuses(prior, result)
    save_job_plan(plan, path, statuses=final)  # re-save with fresh progress
    _, failed, _ = _print_counts(final)
    return 1 if failed else 0


def _cmd_run(args: argparse.Namespace, factory: ExecutorFactory) -> int:
    return _execute(args.plan, factory, resume=False)


def _cmd_resume(args: argparse.Namespace, factory: ExecutorFactory) -> int:
    return _execute(args.plan, factory, resume=True)


def _cmd_status(args: argparse.Namespace, _factory: ExecutorFactory) -> int:
    _print_counts(load_step_statuses(args.plan))
    return 0


# --- argument parsing ------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.jobs",
        description="Create, run, resume, and inspect AbletonGPT job plans.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser(
        "create", help="Build a job plan JSON from an arrangement plan JSON."
    )
    create.add_argument(
        "--arrangement", required=True, help="Path to an arrangement plan JSON file."
    )
    create.add_argument(
        "--out", required=True, help="Path to write the resulting job plan JSON."
    )
    create.set_defaults(func=_cmd_create)

    run = sub.add_parser("run", help="Execute every step of a job plan JSON.")
    run.add_argument("--plan", required=True, help="Path to a job plan JSON file.")
    run.set_defaults(func=_cmd_run)

    resume = sub.add_parser(
        "resume", help="Execute a job plan, skipping already-completed steps."
    )
    resume.add_argument("--plan", required=True, help="Path to a job plan JSON file.")
    resume.set_defaults(func=_cmd_resume)

    status = sub.add_parser(
        "status", help="Show completed/failed/pending counts without executing."
    )
    status.add_argument("--plan", required=True, help="Path to a job plan JSON file.")
    status.set_defaults(func=_cmd_status)

    return parser


def main(argv: list[str] | None = None, *, executor_factory: ExecutorFactory | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 1 on any failed step).

    ``executor_factory`` lets callers (and tests) substitute the executor that runs
    each step; it defaults to a real :class:`AbletonStepExecutor`.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    factory = executor_factory or _default_executor_factory
    return args.func(args, factory)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
