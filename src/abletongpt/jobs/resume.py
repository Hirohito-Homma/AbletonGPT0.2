from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .models import StepStatus
from .runner import JobRunner, JobRunResult, StepExecutor
from .store import load_job_plan, load_step_statuses, save_job_plan

# Statuses that mean "done" — a resume must never re-run these.
COMPLETED_STATUSES = (StepStatus.SUCCEEDED, StepStatus.SKIPPED)


def completed_step_ids(statuses: Mapping[str, StepStatus]) -> tuple[str, ...]:
    """Step ids that a resume must skip because they already finished.

    A step counts as finished when its saved status is ``SUCCEEDED`` or ``SKIPPED``.
    ``PENDING`` and ``FAILED`` steps are intentionally excluded so they run again.
    """
    return tuple(
        step_id
        for step_id, status in statuses.items()
        if status in COMPLETED_STATUSES
    )


def merge_statuses(
    prior: Mapping[str, StepStatus], result: JobRunResult
) -> dict[str, StepStatus]:
    """Overlay a run's outcomes onto the prior statuses.

    Steps the runner reported as ``SKIPPED`` were already done before this run, so their
    *original* status is preserved (a previously ``SUCCEEDED`` step is not demoted to
    ``SKIPPED``). Every step that actually ran contributes its fresh outcome
    (``SUCCEEDED`` / ``FAILED`` / ``PENDING``).
    """
    merged = dict(prior)
    for step_result in result.results:
        if step_result.status is StepStatus.SKIPPED:
            continue
        merged[step_result.step_id] = step_result.status
    return merged


def run_saved_job_plan(
    path: str | Path,
    executor: StepExecutor,
    *,
    max_attempts: int = 1,
    stop_on_error: bool = True,
    save_back: bool = True,
) -> JobRunResult:
    """Load a persisted JobPlan and run only its unfinished steps.

    The plan and its per-step statuses are read from ``path`` (as written by
    :func:`~abletongpt.jobs.store.save_job_plan`). Steps saved as ``SUCCEEDED`` or
    ``SKIPPED`` are handed to :class:`~abletongpt.jobs.runner.JobRunner` as
    ``completed_step_ids`` and never re-executed; ``PENDING`` and ``FAILED`` steps run,
    with ``FAILED`` steps retried up to ``max_attempts`` times.

    When ``save_back`` is true (the default), ``path`` is rewritten with the merged
    post-run status of every step, so a later call resumes exactly where this one
    stopped. Pass ``save_back=False`` to leave the file untouched (dry run).

    Returns the :class:`~abletongpt.jobs.runner.JobRunResult` from the run. This adds no
    new mutation or persistence behavior — it only composes the existing loader, runner,
    and saver.
    """
    plan = load_job_plan(path)
    prior = load_step_statuses(path)

    result = JobRunner(executor).run(
        plan,
        completed_step_ids=completed_step_ids(prior),
        max_attempts=max_attempts,
        stop_on_error=stop_on_error,
    )

    if save_back:
        save_job_plan(plan, path, statuses=merge_statuses(prior, result))

    return result
