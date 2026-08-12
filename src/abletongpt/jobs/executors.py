from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Callable, Protocol, runtime_checkable

from ..bridge import AbletonBridge, AbletonConnectionError
from ..drumkits import build_drum_kit_selection
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


#: Bounds on the read-only browser walk that resolves a kit name to a folder
#: path. The Core Library drum tree is one level of group folders holding kits,
#: but a user library can nest deeper, so allow a little room and cap the total
#: work either way. Browsing is read-only, so an exhausted budget is a failure
#: to find a kit, never a partial change.
_MAX_BROWSER_DEPTH = 3
_MAX_BROWSER_CALLS = 64


def _kit_key(name: str) -> str:
    """A browser item's name reduced to the kit name a selector would use.

    Live's browser reports presets with their file extension -- the verified
    ``drums`` root lists ``"909 Core Kit.adg"``, not ``"909 Core Kit"`` -- while
    :mod:`abletongpt.drumkits` names kits musically and knows nothing about file
    formats. Normalising here keeps it that way; the *unstripped* name is what
    gets loaded, because that is the one ``load_preset`` matches on.
    """

    stripped = name.strip()
    return stripped[:-4] if stripped.lower().endswith(".adg") else stripped


def _drum_kit_locations(
    bridge: SupportsBridgeCall,
    stop_when_found: str = "",
) -> dict[str, tuple[list[str], str]]:
    """Map each loadable kit under the ``drums`` root to its (path, browser name).

    The location is discovered rather than assumed. Live's browser tree is a fact
    about the installation -- on the verified machine the ``drums`` root is flat,
    holding 627 items from Core Library and Packs side by side, but a user
    library can nest -- and neither KIHACHI nor :mod:`abletongpt.drumkits` is
    allowed to know it. Walking is breadth-first so the shallowest match for a
    duplicated kit name wins (``Fabrik Kit`` ships in both Core Library and a
    Pack), which is the one a person would have clicked.

    ``stop_when_found`` ends the walk the moment the caller's *first-choice* kit
    turns up, because nothing found later can outrank it. This is not a
    micro-optimisation: the ``drums`` root also holds a ``Drum Hits`` folder of
    individual samples, and walking it on the verified machine enumerated 7689
    items in 13s -- per drum track -- where stopping at the root finds the kit in
    one call. When the first choice is genuinely absent the full bounded walk
    still runs, so fallback behaviour is unchanged.
    """

    found: dict[str, tuple[list[str], str]] = {}
    queue: list[list[str]] = [[]]
    calls = 0
    while queue and calls < _MAX_BROWSER_CALLS:
        if stop_when_found and stop_when_found in found:
            break
        path = queue.pop(0)
        calls += 1
        listing = bridge.call("browse_presets", category="drums", path=list(path), max_items=1000)
        items = listing.get("items", []) if isinstance(listing, Mapping) else []
        if not isinstance(items, list):
            raise RuntimeError("browse_presets returned an invalid item list")
        for item in items:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            if item.get("is_folder"):
                if len(path) < _MAX_BROWSER_DEPTH:
                    queue.append(path + [name])
                continue
            if not item.get("is_loadable"):
                continue
            key = _kit_key(name)
            if key not in found:
                found[key] = (list(path), name)
    return found


def apply_live_drum_kit(bridge: SupportsBridgeCall, params: dict) -> Any:
    """Load exactly one Browser drum kit onto one empty Drums track.

    Public because the ``apply_live_drum_kit`` MCP tool calls it directly. Both
    entry points must resolve, load and verify identically -- a second
    implementation on the server side is exactly how the two paths would drift.

    The counterpart of :func:`_apply_live_instrument_selection` for the one role
    that device insertion cannot serve. KIHACHI names the musical intent (track,
    role, genre, mood); AbletonGPT owns the kit names, their order, where they
    live in the browser and the readback that proves one kit arrived.

    Safety is the same shape as instrument selection and is enforced twice: this
    handler refuses a track that already holds a *different* instrument, and the
    Remote Script's ``load_preset`` refuses an instrument-category load onto an
    occupied track independently. A track already holding a candidate kit is
    treated as done, so a resumed job never stacks a second rack.
    """

    _exact_params(
        params,
        required=("track_index", "role", "genre", "mood"),
        optional=("live_edition", "preferred_kit"),
    )
    track_index = _non_negative_index(params["track_index"], "track_index")
    values: dict[str, str] = {}
    for field in ("role", "genre", "mood"):
        value = params[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s must be a non-empty string" % field)
        values[field] = value.strip()
    # Accepted and ignored: a kit is a Browser preset, so unlike a native device
    # its availability does not follow the Live edition. Taking the field keeps
    # one KIHACHI operation shape for both instrument paths.
    live_edition = params.get("live_edition", "unknown")
    if not isinstance(live_edition, str) or not live_edition.strip():
        raise ValueError("live_edition must be a non-empty string")
    preferred = params.get("preferred_kit", "")
    if not isinstance(preferred, str):
        raise ValueError("preferred_kit must be a string")

    selection = build_drum_kit_selection(
        values["genre"], values["mood"], values["role"], preferred.strip()
    )
    candidates = list(selection["candidates"])

    existing = _instrument_devices(bridge, track_index)
    if existing:
        if _has_one_matching_instrument(existing, candidates):
            return None
        raise ValueError(
            "target track already contains a different instrument; refusing to replace it"
        )

    locations = _drum_kit_locations(bridge, stop_when_found=candidates[0])
    chosen = next((name for name in candidates if name in locations), None)
    if chosen is None:
        raise RuntimeError(
            "no candidate drum kit found in Live's browser (looked for: %s)"
            % ", ".join(candidates)
        )
    path, browser_name = locations[chosen]

    call_params = {
        "track_index": track_index,
        "category": "drums",
        "path": path,
        "name": browser_name,
    }
    try:
        result = bridge.call("load_preset", _timeout=30.0, **call_params)
    except (AbletonConnectionError, RuntimeError):
        # Loading a rack can outrun the socket while still succeeding in Live.
        # Only an exact readback turns that ambiguity into success.
        if _has_one_matching_instrument(
            _instrument_devices(bridge, track_index), [chosen]
        ):
            return None
        raise
    if not _has_one_matching_instrument(
        _instrument_devices(bridge, track_index), [chosen]
    ):
        raise RuntimeError("Live drum kit readback does not match the loaded kit")
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


def _resolve_scene_index(bridge: SupportsBridgeCall, source_scene: str) -> int:
    """Return the Live scene index for a canonical source_scene name."""
    state = bridge.call("get_state")
    scenes = state.get("scenes", []) if isinstance(state, Mapping) else []
    if not isinstance(scenes, list):
        raise RuntimeError("get_state returned an invalid scene list")
    normalized = source_scene.strip().lower()
    for index, name in enumerate(scenes):
        if isinstance(name, str) and name.strip().lower() == normalized:
            return index
    raise ValueError("source scene %r not found in Live set" % source_scene)


def _place_scene(bridge: SupportsBridgeCall, params: dict) -> Any:
    """Copy an existing Session scene into the Arrangement at the requested bar."""
    _exact_params(
        params,
        required=("source_scene", "start_bar", "length_bars"),
        optional=("transition",),
    )
    source_scene = params["source_scene"]
    if not isinstance(source_scene, str) or not source_scene.strip():
        raise ValueError("source_scene must be a non-empty string")
    start_bar = params["start_bar"]
    length_bars = params["length_bars"]
    if isinstance(start_bar, bool) or not isinstance(start_bar, int):
        raise ValueError("start_bar must be an integer")
    if start_bar < 0:
        raise ValueError("start_bar must be non-negative")
    if isinstance(length_bars, bool) or not isinstance(length_bars, int):
        raise ValueError("length_bars must be an integer")
    if length_bars <= 0:
        raise ValueError("length_bars must be positive")
    transition = params.get("transition", "none")
    if not isinstance(transition, str):
        raise ValueError("transition must be a string")

    scene_index = _resolve_scene_index(bridge, source_scene)
    destination_time_beats = float(start_bar) * 4.0
    # A copy carries the source clip's length, so `length_bars` cannot resize
    # anything -- it is an assertion about the scene. The Remote Script checks it
    # inside its existing preflight, which means a mismatch refuses the whole
    # placement instead of leaving a wrong-length clip behind.
    return bridge.call(
        "copy_scene_to_arrangement",
        scene_index=scene_index,
        destination_time_beats=destination_time_beats,
        track_indices=None,
        expected_length_beats=float(length_bars) * 4.0,
    )


class AbletonStepExecutor:
    """Connects a :class:`JobStep` to real Ableton operations via the bridge.

    The allowlist covers transport/tempo/read commands plus the six additive
    KIHACHI core operations: create a track, add a role-selected native
    instrument *or* load a role-selected Browser drum kit, create a Session MIDI
    clip, write a send envelope, then copy that clip to the Arrangement. Any other command fails
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
        "apply_live_drum_kit": apply_live_drum_kit,
        "create_midi_clip": _create_midi_clip,
        "set_clip_send_envelope": _set_clip_send_envelope,
        "copy_session_clip_to_arrangement": _copy_session_clip_to_arrangement,
        "place_scene": _place_scene,
    }

    def __init__(self, bridge: SupportsBridgeCall | None = None) -> None:
        # AbletonBridge() reads config but does not connect until ``call`` is invoked.
        self._bridge: SupportsBridgeCall = bridge or AbletonBridge()

    @property
    def bridge(self) -> SupportsBridgeCall:
        """The Live connection, for read-only preflight checks before a run.

        Exposed so the CLI can verify the Set matches the plan's track baseline
        without constructing a second bridge. An executor that has no bridge (a
        test fake) simply does not offer this, and the check is skipped.
        """
        return self._bridge

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
