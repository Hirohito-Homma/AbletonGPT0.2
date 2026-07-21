from __future__ import annotations

from dataclasses import dataclass

from .models import ArrangementPlan


@dataclass(frozen=True)
class PlaceSceneOperation:
    """A single deterministic instruction to place a Session scene into the Arrangement.

    This is a plan-only value object. Applying it to Live is intentionally out of scope.
    """

    source_scene: str
    start_bar: int
    length_bars: int
    transition: str = "none"


def build_operations(plan: ArrangementPlan) -> list[PlaceSceneOperation]:
    """Turn an ArrangementPlan into ordered PlaceSceneOperations.

    Operation order mirrors ``plan.sections`` exactly.
    """
    return [
        PlaceSceneOperation(
            source_scene=section.source_scene,
            start_bar=section.start_bar,
            length_bars=section.length_bars,
            transition=section.transition,
        )
        for section in plan.sections
    ]
