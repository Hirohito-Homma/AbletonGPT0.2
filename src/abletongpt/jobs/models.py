from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    """Lifecycle state of a single job step."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class JobStep:
    """One executable unit of work.

    A JobStep is a serializable command name plus parameters. It deliberately does
    not reference any MCP tool or Live object; an executor decides how ``command`` is
    carried out. This keeps the plan a pure, testable intermediate representation.
    """

    step_id: str
    command: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobPlan:
    """An ordered, deterministic sequence of JobSteps. No execution happens here."""

    name: str
    steps: tuple[JobStep, ...] = ()

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.steps)
