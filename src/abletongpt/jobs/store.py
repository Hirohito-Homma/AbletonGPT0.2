from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .models import JobPlan, JobStep, StepStatus

SCHEMA_VERSION = 1


def _step_to_dict(step: JobStep, status: StepStatus) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "command": step.command,
        "params": dict(step.params),
        "status": status.value,
    }


def _plan_to_dict(
    job_plan: JobPlan, statuses: Mapping[str, StepStatus] | None
) -> dict[str, Any]:
    statuses = statuses or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "name": job_plan.name,
        "steps": [
            _step_to_dict(step, statuses.get(step.step_id, StepStatus.PENDING))
            for step in job_plan.steps
        ],
    }


def save_job_plan(
    job_plan: JobPlan,
    path: str | Path,
    *,
    statuses: Mapping[str, StepStatus] | None = None,
) -> Path:
    """Serialize ``job_plan`` (and per-step progress) to a JSON file at ``path``.

    ``statuses`` maps ``step_id`` -> :class:`StepStatus`; any step absent from it is
    recorded as ``PENDING``. Parent directories are created as needed. Accepts either a
    ``str`` or a :class:`pathlib.Path` and returns the resolved :class:`Path` written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _plan_to_dict(job_plan, statuses)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def _read_document(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_job_plan(path: str | Path) -> JobPlan:
    """Reconstruct a :class:`JobPlan` from a file written by :func:`save_job_plan`.

    The returned plan equals the original one that was saved (per-step status is stored
    alongside but is not part of the plan; read it with :func:`load_step_statuses`).
    """
    document = _read_document(path)
    steps = tuple(
        JobStep(
            step_id=raw["step_id"],
            command=raw["command"],
            params=dict(raw.get("params", {})),
        )
        for raw in document.get("steps", [])
    )
    return JobPlan(name=document["name"], steps=steps)


def load_step_statuses(path: str | Path) -> dict[str, StepStatus]:
    """Return the persisted ``step_id`` -> :class:`StepStatus` map from ``path``."""
    document = _read_document(path)
    return {
        raw["step_id"]: StepStatus(raw.get("status", StepStatus.PENDING.value))
        for raw in document.get("steps", [])
    }
