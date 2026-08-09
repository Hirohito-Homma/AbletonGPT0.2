from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Callable, Protocol, runtime_checkable

from ..bridge import AbletonBridge, AbletonConnectionError
from ..instruments import build_role_selection
from .models import JobStep


@runtime_checkable
class SupportsBridgeCall(Protocol):
    """Anything that can dispatch an Ableton command, e.g. :class:`AbletonBridge`.

    Kept minimal so tests can inject a fake without a live Ableton connection.
    """

    def call(self, command: str, **params: Any) -> Any: ...


class UnsupportedStepCommand(ValueError):
    """Raised when a :class:`JobStep` command has no executor mapping yet.

    A subclass of ``ValueError`` so :class:`~abletongpt.jobs.runner.JobRunner`
    records the step as FAILED rather than crashing the whole run: unknown commands
    fail safely, one step at a time.
    """


# Handler signature: (bridge, params) -> the bridge result (discarded by ``execute``).
_Handler = Callable[[SupportsBridgeCall, dict], Any]


def _exact_params(
    params: Mapping[str, Any],
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    """Reject missing and unexpected bridge parameters before any mutation."""
    missing = [key for key in required if key not in params]
    if missing:
        raise KeyError(missing[0])
    unexpected = sorted(set(params) - set(required) - set(optional))
    if unexpected:
        raise ValueError("unexpected parameter(s): %s" % ", ".join(unexpected))


def _finite_number(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("%s must be finite" % label)
    return number


def _non_negative_index(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer" % label)
    index = value
    if index < 0:
        raise ValueError("%s must be non-negative" % label)
    return index


def _play(bridge: SupportsBridgeCall, params: dict) -> Any:
    return bridge.call("set_transport", action="play")


def _stop(bridge: SupportsBridgeCall, params: dict) -> Any:
    return bridge.call("set_transport", action="stop")


def _get_tempo(bridge: SupportsBridgeCall, params: dict) -> Any:
    state = bridge.call("get_state")
    return {"tempo": state["tempo"]}


def _set_tempo(bridge: SupportsBridgeCall, params: dict) -> Any:
    # A missing ``bpm`` raises KeyError, which the runner converts to a FAILED step.
    _exact_params(params, required=("bpm",))
    bpm = _finite_number(params["bpm"], "bpm")
    if not 20 <= bpm <= 999:
        raise ValueError("bpm must be between 20 and 999")
    return bridge.call("set_tempo", bpm=bpm)


def _is_playing(bridge: SupportsBridgeCall, params: dict) -> Any:
    state = bridge.call("get_state")
    return {"is_playing": state["is_playing"]}


def _get_tracks(bridge: SupportsBridgeCall, params: dict) -> Any:
    state = bridge.call("get_state")
    return {"tracks": state["tracks"]}


def _create_track(bridge: SupportsBridgeCall, params: dict) -> Any:
    _exact_params(
        params,
        required=("track_type",),
        optional=("name", "index"),
    )
    track_type = params["track_type"]
    if track_type not in {"midi", "audio"}:
        raise ValueError("track_type must be 'midi' or 'audio'")
    name = params.get("name", "")
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    if len(name) > 200:
        raise ValueError("name must be 200 characters or fewer")
    index = params.get("index", -1)
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError("index must be an integer")
    if index < -1:
        raise ValueError("index must be -1 or non-negative")
    return bridge.call(
        "create_track", track_type=track_type, name=name, index=index
    )


def _instrument_devices(
    bridge: SupportsBridgeCall, track_index: int
) -> list[Mapping[str, Any]]:
    observed = bridge.call("get_track_devices", track_index=track_index)
    devices = observed.get("devices", [])
    if not isinstance(devices, list):
        raise RuntimeError("get_track_devices returned an invalid device list")
    return [
        device
        for device in devices
        if isinstance(device, Mapping) and int(device.get("type", -1)) == 1
    ]


def _instrument_matches(
    device: Mapping[str, Any], candidates: list[str]
) -> bool:
    names = {
        str(device.get(field, "")).strip()
        for field in ("name", "class_name", "class_display_name")
    }
    return any(candidate in names for candidate in candidates)


def _has_one_matching_instrument(
    devices: list[Mapping[str, Any]], candidates: list[str]
) -> bool:
    return len(devices) == 1 and _instrument_matches(devices[0], candidates)


def _apply_live_instrument_selection(
    bridge: SupportsBridgeCall, params: dict
) -> Any:
    """Resolve a semantic role to additive native-instrument candidates.

    KIHACHI names the musical role, genre and mood; AbletonGPT owns Live's
    device allowlist and fallback order. A matching instrument found during
    resume is accepted, while any different existing instrument is left alone
    and fails safely.
    """

    _exact_params(
        params,
        required=("track_index", "role", "genre", "mood"),
        optional=("live_edition", "preferred_instrument", "index"),
    )
    track_index = _non_negative_index(params["track_index"], "track_index")
    values: dict[str, str] = {}
    for field in ("role", "genre", "mood"):
        value = params[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s must be a non-empty string" % field)
        values[field] = value.strip()
    live_edition = params.get("live_edition", "unknown")
    if not isinstance(live_edition, str) or not live_edition.strip():
        raise ValueError("live_edition must be a non-empty string")
    preferred = params.get("preferred_instrument", "")
    if not isinstance(preferred, str):
        raise ValueError("preferred_instrument must be a string")
    index = params.get("index", -1)
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError("index must be an integer")
    if index < -1:
        raise ValueError("index must be -1 or non-negative")

    selection = build_role_selection(
        values["role"],
        values["genre"],
        values["mood"],
        live_edition.strip(),
        preferred.strip(),
    )
    candidates = list(selection["candidates"])
    existing = _instrument_devices(bridge, track_index)
    if existing:
        if _has_one_matching_instrument(existing, candidates):
            return None
        raise ValueError(
            "target track already contains a different instrument; refusing to replace it"
        )

    call_params = {
        "track_index": track_index,
        "candidates": candidates,
        "index": index,
    }
    try:
        result = bridge.call("insert_first_available_instrument", **call_params)
    except (AbletonConnectionError, RuntimeError):
        if _has_one_matching_instrument(
            _instrument_devices(bridge, track_index), candidates
        ):
            return None
        raise
    if not _has_one_matching_instrument(
        _instrument_devices(bridge, track_index), candidates
    ):
        raise RuntimeError("Live instrument readback does not match the selected candidates")
    return result


def _create_midi_clip(bridge: SupportsBridgeCall, params: dict) -> Any:
    _exact_params(
        params,
        required=("track_index", "clip_index", "name", "length_beats", "notes"),
    )
    track_index = _non_negative_index(params["track_index"], "track_index")
    clip_index = _non_negative_index(params["clip_index"], "clip_index")
    name = params["name"]
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    if len(name) > 200:
        raise ValueError("name must be 200 characters or fewer")
    length_beats = _finite_number(params["length_beats"], "length_beats")
    if not 0 < length_beats <= 4096:
        raise ValueError("length_beats must be between 0 and 4096")
    notes = params["notes"]
    if not isinstance(notes, list):
        raise ValueError("notes must be a list")
    if len(notes) > 4096:
        raise ValueError("a clip may contain at most 4096 notes per request")
    note_onsets: set[tuple[int, float]] = set()
    for position, note in enumerate(notes):
        if not isinstance(note, Mapping):
            raise ValueError("note %d must be an object" % position)
        _exact_params(
            note,
            required=("pitch", "start_time", "duration"),
            optional=("velocity", "mute"),
        )
        pitch = note["pitch"]
        if isinstance(pitch, bool) or not isinstance(pitch, int):
            raise ValueError("note pitch must be an integer")
        start = _finite_number(note["start_time"], "note start_time")
        duration = _finite_number(note["duration"], "note duration")
        velocity = _finite_number(note.get("velocity", 100), "note velocity")
        if not 0 <= pitch <= 127:
            raise ValueError("note pitch must be between 0 and 127")
        if start < 0 or start >= length_beats or duration <= 0:
            raise ValueError("note timing is outside the clip")
        if not 0 <= velocity <= 127:
            raise ValueError("note velocity must be between 0 and 127")
        if "mute" in note and not isinstance(note["mute"], bool):
            raise ValueError("note mute must be a boolean")
        onset = (pitch, start)
        if onset in note_onsets:
            raise ValueError(
                "notes must not share pitch and start_time; Live would merge them"
            )
        note_onsets.add(onset)
    call_params = {
        "track_index": track_index,
        "clip_index": clip_index,
        "name": name,
        "length_beats": length_beats,
        "notes": notes,
    }
    try:
        # A long KIHACHI clip can take more than the bridge's general 3-second
        # timeout to materialise in Live. Keep the longer wait local to this one
        # known-heavy operation.
        result = bridge.call("create_midi_clip", _timeout=30.0, **call_params)
        if not _created_clip_matches(bridge, call_params):
            raise RuntimeError("Live MIDI clip readback does not match requested notes")
        return result
    except AbletonConnectionError:
        # The request may have completed in Live after our socket timed out. Only
        # turn that ambiguous outcome into success when a full readback matches.
        if _created_clip_matches(bridge, call_params):
            return None
        raise
    except RuntimeError as exc:
        # Resume after the same ambiguous outcome reaches an occupied slot. It is
        # idempotent only when the existing clip is exactly the reviewed result.
        if str(exc) == "target clip slot is not empty" and _created_clip_matches(
            bridge, call_params
        ):
            return None
        raise


def _created_clip_matches(
    bridge: SupportsBridgeCall, expected: Mapping[str, Any]
) -> bool:
    observed = bridge.call(
        "get_midi_clip_notes",
        track_index=expected["track_index"],
        clip_index=expected["clip_index"],
    )
    if observed.get("truncated"):
        return False
    if observed.get("clip") != expected["name"]:
        return False
    if (
        abs(float(observed.get("length_beats", -1)) - expected["length_beats"])
        > 1e-6
    ):
        return False
    actual_notes = observed.get("notes", [])
    expected_notes = expected["notes"]
    if len(actual_notes) != len(expected_notes):
        return False
    # Live returns notes in its own order and quantises beat values at a much
    # finer resolution than KIHACHI writes. Canonicalise order, then compare every
    # musical field within one micro-beat; count/name/length alone are not enough.
    def ordered(notes):
        return sorted(
            notes,
            key=lambda note: (
                int(note["pitch"]),
                float(note["start_time"]),
                float(note["duration"]),
                float(note.get("velocity", 100)),
            ),
        )

    for wanted, found in zip(ordered(expected_notes), ordered(actual_notes)):
        if int(wanted["pitch"]) != int(found["pitch"]):
            return False
        if abs(float(wanted["start_time"]) - float(found["start_time"])) > 1e-6:
            return False
        if abs(float(wanted["duration"]) - float(found["duration"])) > 1e-6:
            return False
        if float(wanted.get("velocity", 100)) != float(found.get("velocity", 100)):
            return False
        if bool(wanted.get("mute", False)):
            # get_midi_clip_notes does not expose mute, so a muted source cannot
            # be proven identical and must remain a safe failure.
            return False
    return True


def _set_clip_send_envelope(bridge: SupportsBridgeCall, params: dict) -> Any:
    _exact_params(
        params,
        required=("track_index", "clip_index", "send_index", "steps"),
    )
    track_index = _non_negative_index(params["track_index"], "track_index")
    clip_index = _non_negative_index(params["clip_index"], "clip_index")
    send_index = _non_negative_index(params["send_index"], "send_index")
    steps = params["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    if len(steps) > 512:
        raise ValueError("steps must contain at most 512 entries")
    for position, step in enumerate(steps):
        if not isinstance(step, Mapping):
            raise ValueError("step %d must be an object" % position)
        _exact_params(step, required=("start", "length", "value"))
        start = _finite_number(step["start"], "step start")
        length = _finite_number(step["length"], "step length")
        value = _finite_number(step["value"], "step value")
        if start < 0:
            raise ValueError("step start must be non-negative")
        if length <= 0:
            raise ValueError("step length must be positive")
        if not 0 <= value <= 1:
            raise ValueError("a send value must be between 0.0 and 1.0")
    # The public operation has its own name, but both device and send envelopes
    # deliberately share the Remote Script's set_clip_envelope bridge command.
    return bridge.call(
        "set_clip_envelope",
        track_index=track_index,
        clip_index=clip_index,
        send_index=send_index,
        steps=steps,
    )


def _copy_session_clip_to_arrangement(
    bridge: SupportsBridgeCall, params: dict
) -> Any:
    _exact_params(
        params,
        required=("track_index", "clip_index", "destination_time_beats"),
        optional=("name",),
    )
    track_index = _non_negative_index(params["track_index"], "track_index")
    clip_index = _non_negative_index(params["clip_index"], "clip_index")
    destination = _finite_number(
        params["destination_time_beats"], "destination_time_beats"
    )
    if not 0 <= destination <= 1576800:
        raise ValueError("destination_time_beats is outside Live's supported range")
    name = params.get("name", "")
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    if len(name) > 200:
        raise ValueError("name must be 200 characters or fewer")
    return bridge.call(
        "copy_session_clip_to_arrangement",
        track_index=track_index,
        clip_index=clip_index,
        destination_time_beats=destination,
        name=name,
    )


class AbletonStepExecutor:
    """Connects a :class:`JobStep` to real Ableton operations via the bridge.

    The allowlist covers transport/tempo/read commands plus the five additive
    KIHACHI core operations: create a track, add a role-selected native
    instrument, create a Session MIDI clip, write a send envelope, then copy that
    clip to the Arrangement. Any other command fails
    safely as an :class:`UnsupportedStepCommand`. Bridge/connection errors are **not** swallowed;
    they propagate so :class:`~abletongpt.jobs.runner.JobRunner` records the step as
    FAILED with the error text. Satisfies the ``StepExecutor`` protocol.
    """

    #: command name -> handler. Public so callers can inspect what is supported.
    HANDLERS: dict[str, _Handler] = {
        "play": _play,
        "stop": _stop,
        "get_tempo": _get_tempo,
        "set_tempo": _set_tempo,
        "is_playing": _is_playing,
        "get_tracks": _get_tracks,
        "create_track": _create_track,
        "apply_live_instrument_selection": _apply_live_instrument_selection,
        "create_midi_clip": _create_midi_clip,
        "set_clip_send_envelope": _set_clip_send_envelope,
        "copy_session_clip_to_arrangement": _copy_session_clip_to_arrangement,
    }

    def __init__(self, bridge: SupportsBridgeCall | None = None) -> None:
        # AbletonBridge() reads config but does not connect until ``call`` is invoked.
        self._bridge: SupportsBridgeCall = bridge or AbletonBridge()

    @property
    def supported_commands(self) -> tuple[str, ...]:
        return tuple(self.HANDLERS)

    def execute(self, step: JobStep) -> None:
        handler = self.HANDLERS.get(step.command)
        if handler is None:
            raise UnsupportedStepCommand(
                "unsupported step command: %r (supported: %s)"
                % (step.command, ", ".join(self.supported_commands))
            )
        handler(self._bridge, step.params)
