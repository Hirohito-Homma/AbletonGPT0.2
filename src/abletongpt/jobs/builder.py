from __future__ import annotations

from ..arrange.models import ArrangementPlan
from ..arrange.operations import build_operations
from .models import JobPlan, JobStep

PLACE_SCENE_COMMAND = "place_scene"
SET_TEMPO_COMMAND = "set_tempo"


def build_job_plan(plan: ArrangementPlan) -> JobPlan:
    """Translate a pure ArrangementPlan into an executable JobPlan.

    When the plan carries a ``tempo`` it becomes a leading ``set_tempo`` step, so the
    Live Set's tempo is established before any scene is placed. Each PlaceSceneOperation
    then becomes one ``place_scene`` JobStep, preserving order. Step ids are deterministic
    and unique (index-prefixed) so a later runner can resume/retry by id even when a scene
    name repeats.
    """
    steps: list[JobStep] = []
    if plan.tempo is not None:
        steps.append(
            JobStep(
                step_id="%02d_%s" % (len(steps), SET_TEMPO_COMMAND),
                command=SET_TEMPO_COMMAND,
                params={"bpm": plan.tempo},
            )
        )

    for operation in build_operations(plan):
        steps.append(
            JobStep(
                step_id="%02d_%s_%s"
                % (len(steps), PLACE_SCENE_COMMAND, operation.source_scene),
                command=PLACE_SCENE_COMMAND,
                params={
                    "source_scene": operation.source_scene,
                    "start_bar": operation.start_bar,
                    "length_bars": operation.length_bars,
                    "transition": operation.transition,
                },
            )
        )
    return JobPlan(name=plan.name, steps=tuple(steps))
