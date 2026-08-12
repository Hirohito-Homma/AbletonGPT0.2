"""Pure adapter from a KIHACHI arrangement plan to an AbletonGPT job plan.

The adapter is intentionally narrow. It accepts the existing tempo command and the
six additive core operations needed for a native-instrument-ready MIDI
arrangement with send throws. Any other operation rejects the *whole* document
before a real bridge can be opened.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..drumkits import ALL_KIT_NAMES
from .executors import AbletonStepExecutor
from .models import JobPlan, JobStep

KIHACHI_ARRANGEMENT_PLAN_VERSION = "0.1"
KIHACHI_CORE_COMMANDS = frozenset(
    {
        "set_tempo",
        "create_track",
        "apply_live_instrument_selection",
        "apply_live_drum_kit",
        "create_midi_clip",
        "set_clip_send_envelope",
        "copy_session_clip_to_arrangement",
    }
)


class InvalidKihachiPlan(ValueError):
    """Raised when a KIHACHI document is unsafe or outside the core contract."""


class _ValidationBridge:
    """A bridge-shaped sink used to run executor validation without Live I/O."""

    def __init__(self) -> None:
        self._clips: dict[tuple[int, int], dict[str, Any]] = {}
        self._devices: dict[int, list[dict[str, Any]]] = {}

    def call(self, command: str, **params: Any) -> dict[str, Any]:
        if command == "get_track_devices":
            return {"devices": list(self._devices.get(params["track_index"], []))}
        if command == "insert_first_available_instrument":
            candidate = params["candidates"][0]
            device = {
                "name": candidate,
                "class_name": candidate,
                "class_display_name": candidate,
                "type": 1,
            }
            self._devices.setdefault(params["track_index"], []).append(device)
            return {"name": candidate}
        if command == "browse_presets":
            # Preflight runs with no Live and therefore no browser. Standing in
            # every kit the selector can name checks the walk and the load
            # parameters; whether a given kit is actually installed is a question
            # only the real browser can answer, and the executor asks it there.
            if params["path"]:
                return {"items": []}
            # ``.adg`` because that is how the real browser reports a preset,
            # so the preflight exercises the same name normalisation the
            # executor does against Live rather than an easier fiction.
            return {
                "items": [
                    {"name": name + ".adg", "is_folder": False, "is_loadable": True}
                    for name in sorted(ALL_KIT_NAMES)
                ]
            }
        if command == "load_preset":
            # Live names the resulting device after the preset, without the
            # extension -- which is what the executor's readback compares to.
            loaded = params["name"]
            if loaded.lower().endswith(".adg"):
                loaded = loaded[:-4]
            device = {
                "name": loaded,
                "class_name": "DrumGroupDevice",
                "class_display_name": "Drum Rack",
                "type": 1,
            }
            self._devices.setdefault(params["track_index"], []).append(device)
            return {"loaded": params["name"], "verified_single_add": True}
        if command == "create_midi_clip":
            self._clips[(params["track_index"], params["clip_index"])] = {
                "clip": params["name"],
                "length_beats": params["length_beats"],
                "truncated": False,
                "notes": list(params["notes"]),
            }
        if command == "get_midi_clip_notes":
            return self._clips[(params["track_index"], params["clip_index"])]
        return {}


def _step_id(position: int, command: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", command.lower()).strip("_")
    return "%04d_%s" % (position, slug or "step")


def build_kihachi_job_plan(document: Mapping[str, Any]) -> JobPlan:
    """Validate and convert one KIHACHI ``arrangement_plan.json`` document.

    Validation is a complete preflight: every operation is checked through the same
    handlers the real executor uses, but against a no-op bridge. Therefore an unknown
    operation or bad parameter in a later step is found before an earlier step can
    create anything in Live.
    """
    if not isinstance(document, Mapping):
        raise InvalidKihachiPlan("KIHACHI arrangement plan must be a JSON object")
    version = document.get("arrangement_plan_version")
    if version != KIHACHI_ARRANGEMENT_PLAN_VERSION:
        raise InvalidKihachiPlan(
            "unsupported KIHACHI arrangement plan version: %r (expected %s)"
            % (version, KIHACHI_ARRANGEMENT_PLAN_VERSION)
        )
    state = document.get("execution_state")
    if state != "planned_not_applied":
        raise InvalidKihachiPlan(
            "execution_state must be 'planned_not_applied' (got %r)" % state
        )

    song = document.get("song")
    if not isinstance(song, Mapping):
        raise InvalidKihachiPlan("song must be a JSON object")
    title = song.get("title")
    if not isinstance(title, str) or not title.strip():
        raise InvalidKihachiPlan("song.title must be a non-empty string")

    operations = document.get("operations")
    if not isinstance(operations, list) or not operations:
        raise InvalidKihachiPlan("operations must be a non-empty list")

    steps: list[JobStep] = []
    validator = AbletonStepExecutor(_ValidationBridge())
    for position, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            raise InvalidKihachiPlan("operation %d must be a JSON object" % position)
        command = operation.get("op")
        if command not in KIHACHI_CORE_COMMANDS:
            raise InvalidKihachiPlan(
                "operation %d uses unsupported KIHACHI core command %r "
                "(allowed: %s)"
                % (position, command, ", ".join(sorted(KIHACHI_CORE_COMMANDS)))
            )
        params = operation.get("params")
        if not isinstance(params, Mapping):
            raise InvalidKihachiPlan(
                "operation %d params must be a JSON object" % position
            )
        step = JobStep(_step_id(position, command), command, dict(params))
        try:
            validator.execute(step)
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidKihachiPlan(
                "operation %d (%s) is invalid: %s" % (position, command, exc)
            ) from exc
        steps.append(step)

    return JobPlan(name=title.strip(), steps=tuple(steps))
