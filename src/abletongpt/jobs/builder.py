from __future__ import annotations

from ..arrange.models import ArrangementPlan
from ..arrange.operations import build_operations
from .models import JobPlan, JobStep

PLACE_SCENE_COMMAND = "place_scene"


def build_job_plan(plan: ArrangementPlan) -> JobPlan:
    """Translate a pure ArrangementPlan into an executable JobPlan.

    Each PlaceSceneOperation becomes one ``place_scene`` JobStep, preserving order.
    Step ids are deterministic and unique (index-prefixed) so a later runner can
    resume/retry by id even when a scene name repeats.
    """
    operations = build_operations(plan)
    steps = tuple(
        JobStep(
            step_id="%02d_%s_%s" % (index, PLACE_SCENE_COMMAND, operation.source_scene),
            command=PLACE_SCENE_COMMAND,
            params={
                "source_scene": operation.source_scene,
                "start_bar": operation.start_bar,
                "length_bars": operation.length_bars,
                "transition": operation.transition,
            },
        )
        for index, operation in enumerate(operations)
    )
    return JobPlan(name=plan.name, steps=steps)
