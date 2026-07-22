from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import JobPlan, JobStep, StepStatus
from .store import save_job_plan


@runtime_checkable
class StepExecutor(Protocol):
    """Carries out a single JobStep.

    This is the seam between the plan and the outside world. The real MCP/Live-backed
    executor is provided by a later PR; tests inject a fake. A failed step raises.
    """

    def execute(self, step: JobStep) -> None: ...


@dataclass(frozen=True)
class StepResult:
    step_id: str
    status: StepStatus
    attempts: int = 0
    error: str | None = None


@dataclass(frozen=True)
class JobRunResult:
    """Immutable record of one run, sufficient to drive resume/retry."""

    results: tuple[StepResult, ...] = ()

    @property
    def succeeded(self) -> bool:
        return all(
            result.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
            for result in self.results
        )

    @property
    def completed_step_ids(self) -> tuple[str, ...]:
        """Ids that need not run again on resume (succeeded or already skipped)."""
        return tuple(
            result.step_id
            for result in self.results
            if result.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
        )

    @property
    def failed_step_ids(self) -> tuple[str, ...]:
        return tuple(
            result.step_id
            for result in self.results
            if result.status is StepStatus.FAILED
        )

    @property
    def pending_step_ids(self) -> tuple[str, ...]:
        """Steps not attempted (e.g. left after an earlier step halted the run)."""
        return tuple(
            result.step_id
            for result in self.results
            if result.status is StepStatus.PENDING
        )


class JobRunner:
    """Executes a JobPlan in order via an injected executor. No Live dependency."""

    def __init__(self, executor: StepExecutor) -> None:
        self._executor = executor

    def run(
        self,
        plan: JobPlan,
        *,
        completed_step_ids: Iterable[str] = (),
        max_attempts: int = 1,
        stop_on_error: bool = True,
        persistence_path: str | Path | None = None,
    ) -> JobRunResult:
        """Run ``plan`` deterministically, top to bottom.

        - resume: steps whose id is in ``completed_step_ids`` are marked SKIPPED and
          never handed to the executor.
        - retry: each step is attempted up to ``max_attempts`` times before FAILED.
        - halt: on failure with ``stop_on_error`` the rest stay PENDING, so a follow-up
          run (passing this result's ``completed_step_ids``) picks up exactly where it left off.
        - persist: when ``persistence_path`` is given, the plan and its per-step statuses
          are saved after every step (via :func:`save_job_plan`), so a crashed or resumed
          run can be reconstructed with :func:`load_job_plan` / :func:`load_step_statuses`.
          When it is ``None`` the run behaves exactly as before and touches no disk.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        already_done = set(completed_step_ids)
        results: list[StepResult] = []
        halted = False

        for step in plan.steps:
            if halted:
                results.append(StepResult(step.step_id, StepStatus.PENDING))
                self._persist(plan, results, persistence_path)
                continue
            if step.step_id in already_done:
                results.append(StepResult(step.step_id, StepStatus.SKIPPED))
                self._persist(plan, results, persistence_path)
                continue

            attempts = 0
            last_error: str | None = None
            status = StepStatus.FAILED
            while attempts < max_attempts:
                attempts += 1
                try:
                    self._executor.execute(step)
                    status = StepStatus.SUCCEEDED
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001 - recorded, not swallowed silently
                    last_error = str(exc)

            results.append(StepResult(step.step_id, status, attempts, last_error))
            self._persist(plan, results, persistence_path)
            if status is StepStatus.FAILED and stop_on_error:
                halted = True

        return JobRunResult(tuple(results))

    @staticmethod
    def _persist(
        plan: JobPlan,
        results: list[StepResult],
        persistence_path: str | Path | None,
    ) -> None:
        """Save ``plan`` with the progress collected so far, if a path was given.

        Steps not yet reached are absent from the status map; ``save_job_plan`` records
        those as PENDING. Parent-directory creation is delegated to ``save_job_plan``.
        """
        if persistence_path is None:
            return
        statuses = {result.step_id: result.status for result in results}
        save_job_plan(plan, persistence_path, statuses=statuses)
