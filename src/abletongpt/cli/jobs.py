"""Command-line entry points for creating, running, and resuming job plans.

    python -m abletongpt.cli.jobs create      --arrangement a.json --out plan.json
    python -m abletongpt.cli.jobs run         --plan plan.json
    python -m abletongpt.cli.jobs resume      --plan plan.json
    python -m abletongpt.cli.jobs status      --plan plan.json
    python -m abletongpt.cli.jobs arrange-run --job-path plan.json

``arrange-run`` is the one-shot path: it generates the default arrangement, builds a
job plan, optionally saves it, and runs it -- all in a single command.

The CLI is a thin wrapper over the existing pure engines and stores: it never talks
to Ableton itself, it hands each :class:`JobStep` to an executor. The executor is
supplied by ``executor_factory`` so tests can inject a fake and stay off the socket;
the default is :class:`~abletongpt.jobs.AbletonStepExecutor`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from .serialization import arrangement_from_dict, read_json_document
from ..arrange.presets import (
    DEFAULT_STYLE,
    UnknownStyleError,
    arrangement_for_style,
    available_styles,
)
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


def _print_available_styles(*, as_json: bool = False) -> None:
    """Print every registered arrange-run style."""
    styles = list(available_styles())
    if as_json:
        print(json.dumps({"styles": styles}, indent=2, sort_keys=True))
        return
    for style in styles:
        print(style)


def _style_description(style: str) -> dict[str, object]:
    """Return a compact, machine-friendly summary for one registered style."""
    arrangement = arrangement_for_style(style, None)
    plan = build_job_plan(arrangement)
    tempo = next(
        (step.params.get("bpm") for step in plan.steps if step.command == "set_tempo"),
        None,
    )
    total_bars = sum(
        int(step.params.get("length_bars", 0))
        for step in plan.steps
        if step.command == "place_scene"
    )
    return {
        "style": style,
        "name": plan.name,
        "step_count": len(plan.steps),
        "tempo": float(tempo) if tempo is not None else None,
        "total_bars": total_bars,
    }


def _print_style_description(style: str, *, as_json: bool = False) -> None:
    """Print a compact summary for one registered arrange-run style."""
    description = _style_description(style)
    if as_json:
        print(json.dumps(description, indent=2, sort_keys=True))
        return
    print("style: %s" % description["style"])
    print(
        "job plan '%s' with %d step(s), tempo=%g, %d bar(s)"
        % (
            description["name"],
            description["step_count"],
            description["tempo"],
            description["total_bars"],
        )
    )


def _print_all_style_descriptions(*, as_json: bool = False) -> None:
    """Print compact summaries for every registered arrange-run style."""
    descriptions = [_style_description(style) for style in available_styles()]
    if as_json:
        print(json.dumps({"styles": descriptions}, indent=2, sort_keys=True))
        return

    for description in descriptions:
        print("style: %s" % description["style"])
        print(
            "job plan '%s' with %d step(s), tempo=%s, %d bar(s)"
            % (
                description["name"],
                description["step_count"],
                (
                    "%g" % description["tempo"]
                    if description["tempo"] is not None
                    else "none"
                ),
                description["total_bars"],
            )
        )


# --- arrange-run orchestration ---------------------------------------------------

def _plan_overview(plan: JobPlan) -> str:
    """Human-readable one-liner describing a job plan (name, steps, tempo, length).

    Tempo and total length are read back out of the steps so this works for both freshly
    generated plans and ones reloaded from disk on ``--resume``.
    """
    parts = ["job plan '%s' with %d step(s)" % (plan.name, len(plan.steps))]
    tempo = next(
        (step.params.get("bpm") for step in plan.steps if step.command == "set_tempo"),
        None,
    )
    if tempo is not None:
        parts.append("tempo=%g" % float(tempo))
    total_bars = sum(
        int(step.params.get("length_bars", 0))
        for step in plan.steps
        if step.command == "place_scene"
    )
    if total_bars:
        parts.append("%d bar(s)" % total_bars)
    return ", ".join(parts)


def _prepare_job_plan(
    *,
    style: str,
    name: str | None,
    job_path: str | None,
    resume: bool,
    tempo: float | None,
    bars: int | None,
) -> tuple[JobPlan, dict[str, StepStatus], tuple[str, ...]]:
    """Return ``(plan, prior_statuses, completed_ids)`` for an arrange-run.

    Resume path: when ``--resume`` is set and ``job_path`` already holds a saved plan,
    reload it plus its progress so completed steps are skipped -- the on-disk plan wins,
    so ``--style``/``--tempo``/``--bars``/``--name`` are deliberately ignored and never
    regenerate it. Otherwise build a fresh arrangement for ``style`` (honoring
    ``name``/``tempo``/``bars``) -> job plan, with empty prior progress. A ``name`` of
    ``None`` (``--name`` omitted) takes the style's own default name. Falling back to a
    fresh build (rather than erroring) keeps ``--resume`` safe to pass on a first run.
    Raises :class:`UnknownStyleError` when a fresh build is asked for an unknown style.
    """
    if resume and job_path and Path(job_path).exists():
        plan = load_job_plan(job_path)
        prior = load_step_statuses(job_path)
        completed = tuple(
            sid for sid, status in prior.items() if status in _COMPLETED
        )
        return plan, prior, completed
    arrangement = arrangement_for_style(style, name, tempo=tempo, total_bars=bars)
    return build_job_plan(arrangement), {}, ()


def run_arrangement(
    factory: ExecutorFactory,
    *,
    style: str = DEFAULT_STYLE,
    name: str | None = None,
    job_path: str | None = None,
    save: bool = True,
    dry_run: bool = False,
    resume: bool = False,
    tempo: float | None = None,
    bars: int | None = None,
) -> int:
    """Build (or reload) an arrangement's job plan and run it end-to-end.

    One-shot glue over the existing engines: ``arrangement_for_style`` -> ``build_job_plan``
    -> optional ``save_job_plan`` -> ``JobRunner`` + the injected executor. ``style`` picks
    the genre preset; ``tempo`` (BPM) and ``bars`` (total length) shape it. ``name`` of
    ``None`` uses the style's own default name. All four are ignored on the ``resume`` path,
    where the saved plan takes precedence. ``dry_run`` prints the plan summary and returns
    without touching the executor or disk. Returns a process exit code (0 ok, 1 if any step
    failed). Raises :class:`UnknownStyleError` for an unknown style on a fresh build.
    """
    plan, prior, completed = _prepare_job_plan(
        style=style,
        name=name,
        job_path=job_path,
        resume=resume,
        tempo=tempo,
        bars=bars,
    )

    if dry_run:
        print("dry-run: would run %s (no execution)" % _plan_overview(plan))
        return 0

    persist = save and job_path is not None
    if persist:
        save_job_plan(plan, job_path, statuses=prior or None)  # persist before running

    result = JobRunner(factory()).run(plan, completed_step_ids=completed)
    final = _merge_statuses(prior, result)

    if persist:
        save_job_plan(plan, job_path, statuses=final)  # re-save with fresh progress

    _, failed, _ = _print_counts(final)
    return 1 if failed else 0


def _cmd_arrange_run(args: argparse.Namespace, factory: ExecutorFactory) -> int:
    if args.list_styles:
        _print_available_styles(as_json=args.json)
        return 0

    try:
        if args.describe_all_styles:
            _print_all_style_descriptions(as_json=args.json)
            return 0

        if args.describe_style is not None:
            _print_style_description(args.describe_style, as_json=args.json)
            return 0

        # Save only when a destination exists and the user did not opt out; there is nothing
        # to persist without ``--job-path``.
        save = args.job_path is not None and not args.no_save
        return run_arrangement(
            factory,
            style=args.style,
            name=args.name,
            job_path=args.job_path,
            save=save,
            dry_run=args.dry_run,
            resume=args.resume,
            tempo=args.tempo,
            bars=args.bars,
        )
    except UnknownStyleError as exc:
        # Turn an unknown --style into a clear, non-zero CLI failure (exit 2, matching
        # argparse's convention for usage errors) rather than a traceback.
        print("arrange-run: %s" % exc, file=sys.stderr)
        return 2


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

    arrange_run = sub.add_parser(
        "arrange-run",
        help="Generate a default arrangement, build a job plan, and run it end-to-end.",
    )
    arrange_run.add_argument(
        "--style",
        default=DEFAULT_STYLE,
        help="Arrangement style preset (default: %(default)s; available: "
        + ", ".join(available_styles())
        + "). Ignored with --resume.",
    )
    arrange_run.add_argument(
        "--list-styles",
        action="store_true",
        help="Print available arrangement style presets and exit without running.",
    )
    arrange_run.add_argument(
        "--describe-style",
        metavar="STYLE",
        default=None,
        help="Print a compact summary for one arrangement style preset and exit.",
    )
    arrange_run.add_argument(
        "--describe-all-styles",
        action="store_true",
        help="Print compact summaries for every arrangement style preset and exit.",
    )
    arrange_run.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit machine-readable JSON for --list-styles, --describe-style, "
            "or --describe-all-styles output."
        ),
    )
    arrange_run.add_argument(
        "--name",
        default=None,
        help="Name for the generated arrangement (default: the style's own name, "
        "e.g. dark_tech_house / deep_house). Ignored with --resume.",
    )
    arrange_run.add_argument(
        "--tempo",
        type=float,
        default=None,
        metavar="BPM",
        help="Song tempo in BPM; adds a leading set_tempo step (ignored with --resume).",
    )
    arrange_run.add_argument(
        "--bars",
        type=int,
        default=None,
        help="Total arrangement length in bars (ignored with --resume).",
    )
    arrange_run.add_argument(
        "--job-path",
        default=None,
        help="Where to save the generated job plan (also read back with --resume).",
    )
    arrange_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the job plan that would run without executing or saving anything.",
    )
    arrange_run.add_argument(
        "--resume",
        action="store_true",
        help="Reload the plan at --job-path and run only its not-yet-completed steps.",
    )
    arrange_run.add_argument(
        "--no-save",
        action="store_true",
        help="Run without saving the job plan, even when --job-path is given.",
    )
    arrange_run.set_defaults(func=_cmd_arrange_run)

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
