"""Guarded selective repair of one Session MIDI clip.

One invocation observes Live, validates identity and preconditions, then performs
at most one approved mutation and verifies the result with a second read. This is
not a general repair engine: it cannot delete clips, rewrite Arrangement, or
chain fallback writes.

The only approved Live write is ``create_midi_clip``, which atomically populates
an empty Session slot. Replacing an existing clip's notes would require the
Remote Script's ``apply_expression_to_clip`` path, which clears then recreates
notes inside one command. That is a destructive multi-step shape, so this
primitive refuses it instead of wrapping it.

    candidate repairable != automatically safe
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .bridge import AbletonConnectionError

ALLOWED_OPERATIONS = ("create_midi_clip",)

STATUS_REPAIRED = "repaired"
STATUS_NOOP = "noop"
STATUS_REFUSED = "refused"
STATUS_FAILED = "failed"

SLOT_EMPTY = "empty"
SLOT_EXISTING = "existing"

REASON_UNSUPPORTED_REPAIR_SHAPE = "unsupported_repair_shape"
REASON_INVALID_INDEX = "invalid_index"
REASON_INVALID_VALUE = "invalid_value"
REASON_MISSING_FIELD = "missing_field"
REASON_MALFORMED_NOTES = "malformed_notes"
REASON_TARGET_NOT_FOUND = "target_not_found"
REASON_TRACK_IDENTITY_MISMATCH = "track_identity_mismatch"
REASON_CLIP_IDENTITY_MISMATCH = "clip_identity_mismatch"
REASON_STATE_PRECONDITION_FAILED = "state_precondition_failed"
REASON_SLOT_OCCUPANCY_MISMATCH = "slot_occupancy_mismatch"
REASON_UNOBSERVABLE_TARGET = "unobservable_target"
REASON_POSTCONDITION_FAILED = "postcondition_failed"
REASON_MUTATION_REJECTED = "mutation_rejected"

MUTATION_CREATE_MIDI_CLIP = "create_midi_clip"

_MUTATION_COMMANDS = frozenset(ALLOWED_OPERATIONS)
_SLOT_STATES = frozenset({SLOT_EMPTY, SLOT_EXISTING})
_NOTE_FIELDS = frozenset(
    {"pitch", "start_time", "duration", "velocity", "mute", "probability"}
)
_EMPTY_SLOT_ERRORS = (
    "target clip slot does not contain a MIDI clip",
)
_LENGTH_TOLERANCE = 1e-6
_TIME_TOLERANCE = 1e-6
_MAX_NOTES = 4096
_MAX_NAME = 200
_MAX_LENGTH = 4096.0


@runtime_checkable
class SupportsBridgeCall(Protocol):
    """Anything that can dispatch an Ableton command, e.g. the Live bridge."""

    def call(self, command: str, **params: Any) -> Any: ...


def _result(
    *,
    status: str,
    operation: str | None,
    target: Mapping[str, Any],
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    mutation_performed: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "operation": operation,
        "target": dict(target),
        "before": dict(before) if before is not None else None,
        "after": dict(after) if after is not None else None,
        "mutation_performed": mutation_performed,
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def _refused(
    reason: str,
    *,
    operation: str | None = None,
    target: Mapping[str, Any] | None = None,
    before: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _result(
        status=STATUS_REFUSED,
        operation=operation,
        target=target or {},
        before=before,
        after=before,
        mutation_performed=False,
        reason=reason,
    )


def _non_negative_index(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer" % label)
    if value < 0:
        raise ValueError("%s must be non-negative" % label)
    return value


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a finite number" % label) from exc
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError("%s must be a finite number" % label)
    return number


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("%s must be a string" % label)
    return value


def _optional_non_negative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _non_negative_index(value, label)


def _values_equivalent(left: Any, right: Any, tolerance: float = _TIME_TOLERANCE) -> bool:
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def canonical_notes(notes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return notes sorted into a stable, order-independent identity.

    Comparison uses the fields ``get_midi_clip_notes`` actually returns. Mute is
    not observable on readback, so it is omitted. Ordering differences alone
    do not change identity.
    """

    normalized = []
    for note in notes:
        normalized.append(
            {
                "pitch": int(note["pitch"]),
                "start_time": float(note["start_time"]),
                "duration": float(note["duration"]),
                "velocity": int(note.get("velocity", 100)),
                "probability": float(note.get("probability", 1.0)),
            }
        )
    normalized.sort(
        key=lambda item: (
            item["pitch"],
            item["start_time"],
            item["duration"],
            item["velocity"],
            item["probability"],
        )
    )
    return normalized


def notes_digest(notes: Sequence[Mapping[str, Any]], length_beats: float | None = None) -> str:
    """Deterministic SHA-256 of canonical notes. Never uses ``hash()``."""

    compact = [
        {
            "pitch": item["pitch"],
            "start_time": round(item["start_time"], 6),
            "duration": round(item["duration"], 6),
            "velocity": item["velocity"],
            "probability": round(item["probability"], 6),
        }
        for item in canonical_notes(notes)
    ]
    payload = {
        "length_beats": None if length_beats is None else round(float(length_beats), 6),
        "notes": compact,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def notes_equivalent(
    left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]
) -> bool:
    first = canonical_notes(left)
    second = canonical_notes(right)
    if len(first) != len(second):
        return False
    for wanted, found in zip(first, second):
        if wanted["pitch"] != found["pitch"]:
            return False
        if wanted["velocity"] != found["velocity"]:
            return False
        if not _values_equivalent(wanted["start_time"], found["start_time"]):
            return False
        if not _values_equivalent(wanted["duration"], found["duration"]):
            return False
        if not _values_equivalent(wanted["probability"], found["probability"]):
            return False
    return True


def _state_view(
    *,
    track_index: int,
    track_name: Any,
    clip_index: int,
    slot_state: str,
    clip_name: Any = None,
    length_beats: Any = None,
    notes: Sequence[Mapping[str, Any]] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    observed_notes = canonical_notes(notes or [])
    length = None if length_beats is None else float(length_beats)
    return {
        "track_index": track_index,
        "track": track_name,
        "clip_index": clip_index,
        "clip": clip_name,
        "slot_state": slot_state,
        "length_beats": length,
        "note_count": len(observed_notes),
        "notes": observed_notes,
        "note_digest": notes_digest(observed_notes, length),
        "truncated": truncated,
    }


def _parse_one_note(
    note: Any, position: int, length_beats: float, *, require_writable: bool
) -> dict[str, Any] | dict[str, Any]:
    if not isinstance(note, Mapping):
        return _refused(REASON_MALFORMED_NOTES)
    extra = set(note) - _NOTE_FIELDS
    if extra:
        return _refused(REASON_MALFORMED_NOTES)
    for field in ("pitch", "start_time", "duration"):
        if field not in note or note.get(field) is None:
            return _refused(REASON_MALFORMED_NOTES)
    pitch = note["pitch"]
    if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
        return _refused(REASON_MALFORMED_NOTES)
    try:
        start = _finite_number(note["start_time"], "note start_time")
        duration = _finite_number(note["duration"], "note duration")
        velocity = _finite_number(note.get("velocity", 100), "note velocity")
        probability = _finite_number(note.get("probability", 1.0), "note probability")
    except ValueError:
        return _refused(REASON_MALFORMED_NOTES)
    if start < 0 or start >= length_beats or duration <= 0:
        return _refused(REASON_MALFORMED_NOTES)
    if not 0 <= velocity <= 127 or int(velocity) != velocity:
        return _refused(REASON_MALFORMED_NOTES)
    if not 0.0 <= probability <= 1.0:
        return _refused(REASON_MALFORMED_NOTES)
    mute = note.get("mute", False)
    if mute is not None and not isinstance(mute, bool):
        return _refused(REASON_MALFORMED_NOTES)
    if require_writable and mute is True:
        return _refused(REASON_UNSUPPORTED_REPAIR_SHAPE)
    if require_writable and not _values_equivalent(probability, 1.0):
        # ``create_midi_clip`` uses clip.set_notes, which cannot write probability.
        return _refused(REASON_UNSUPPORTED_REPAIR_SHAPE)
    if mute is True:
        # get_midi_clip_notes does not expose mute, so a muted current note cannot
        # be used as a proven precondition.
        return _refused(REASON_UNOBSERVABLE_TARGET)
    return {
        "pitch": pitch,
        "start_time": start,
        "duration": min(duration, length_beats - start),
        "velocity": int(velocity),
        "probability": probability,
        "_onset": (pitch, start),
        "_position": position,
    }


def _parse_notes(
    notes: Any, length_beats: float, *, require_writable: bool
) -> list[dict[str, Any]] | dict[str, Any]:
    if not isinstance(notes, list):
        return _refused(REASON_MALFORMED_NOTES)
    if len(notes) > _MAX_NOTES:
        return _refused(REASON_MALFORMED_NOTES)
    parsed: list[dict[str, Any]] = []
    onsets: set[tuple[int, float]] = set()
    for position, note in enumerate(notes):
        item = _parse_one_note(
            note, position, length_beats, require_writable=require_writable
        )
        if isinstance(item, dict) and item.get("status") == STATUS_REFUSED:
            return item
        onset = item["_onset"]
        if onset in onsets:
            return _refused(REASON_MALFORMED_NOTES)
        onsets.add(onset)
        parsed.append(item)
    canonical = canonical_notes(
        [
            {
                "pitch": item["pitch"],
                "start_time": item["start_time"],
                "duration": item["duration"],
                "velocity": item["velocity"],
                "probability": item["probability"],
            }
            for item in parsed
        ]
    )
    return canonical


def _parse_request(request: Mapping[str, Any]) -> dict[str, Any]:
    operation = request.get("operation", MUTATION_CREATE_MIDI_CLIP)
    if not isinstance(operation, str) or operation not in ALLOWED_OPERATIONS:
        return _refused(
            REASON_UNSUPPORTED_REPAIR_SHAPE,
            operation=operation if isinstance(operation, str) else None,
        )

    target: dict[str, Any] = {}
    try:
        track_index = _non_negative_index(request.get("track_index"), "track_index")
        clip_index = _non_negative_index(request.get("clip_index"), "clip_index")
    except ValueError:
        return _refused(REASON_INVALID_INDEX, operation=operation, target=target)
    target["track_index"] = track_index
    target["clip_index"] = clip_index

    expected_slot_state = request.get("expected_slot_state")
    if expected_slot_state is None:
        return _refused(REASON_MISSING_FIELD, operation=operation, target=target)
    if expected_slot_state not in _SLOT_STATES:
        return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    name = request.get("name")
    if not isinstance(name, str):
        return _refused(REASON_MISSING_FIELD, operation=operation, target=target)
    if len(name) > _MAX_NAME:
        return _refused(REASON_INVALID_VALUE, operation=operation, target=target)
    target["clip"] = name

    if "length_beats" not in request or request.get("length_beats") is None:
        return _refused(REASON_MISSING_FIELD, operation=operation, target=target)
    try:
        length_beats = _finite_number(request.get("length_beats"), "length_beats")
    except ValueError:
        return _refused(REASON_INVALID_VALUE, operation=operation, target=target)
    if not 0 < length_beats <= _MAX_LENGTH:
        return _refused(REASON_INVALID_VALUE, operation=operation, target=target)
    target["length_beats"] = length_beats

    if "notes" not in request or request.get("notes") is None:
        return _refused(REASON_MISSING_FIELD, operation=operation, target=target)
    desired_notes = _parse_notes(
        request.get("notes"), length_beats, require_writable=True
    )
    if isinstance(desired_notes, dict) and desired_notes.get("status") == STATUS_REFUSED:
        desired_notes["operation"] = operation
        desired_notes["target"] = target
        return desired_notes
    target["note_count"] = len(desired_notes)
    target["note_digest"] = notes_digest(desired_notes, length_beats)

    try:
        expected_track_name = _optional_text(
            request.get("expected_track_name"), "expected_track_name"
        )
        expected_clip_name = _optional_text(
            request.get("expected_clip_name"), "expected_clip_name"
        )
        expected_note_digest = _optional_text(
            request.get("expected_note_digest"), "expected_note_digest"
        )
        expected_note_count = _optional_non_negative_int(
            request.get("expected_note_count"), "expected_note_count"
        )
    except ValueError:
        return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    expected_clip_length = request.get("expected_clip_length")
    if expected_clip_length is not None:
        try:
            expected_clip_length = _finite_number(
                expected_clip_length, "expected_clip_length"
            )
        except ValueError:
            return _refused(REASON_INVALID_VALUE, operation=operation, target=target)

    expected_notes: list[dict[str, Any]] | None = None
    if "expected_notes" in request and request.get("expected_notes") is not None:
        compare_length = (
            expected_clip_length if expected_clip_length is not None else length_beats
        )
        parsed_expected = _parse_notes(
            request.get("expected_notes"), compare_length, require_writable=False
        )
        if isinstance(parsed_expected, dict) and parsed_expected.get("status") == STATUS_REFUSED:
            parsed_expected["operation"] = operation
            parsed_expected["target"] = target
            return parsed_expected
        expected_notes = parsed_expected

    return {
        "operation": operation,
        "track_index": track_index,
        "clip_index": clip_index,
        "name": name,
        "length_beats": length_beats,
        "notes": desired_notes,
        "expected_slot_state": expected_slot_state,
        "expected_track_name": expected_track_name,
        "expected_clip_name": expected_clip_name,
        "expected_clip_length": expected_clip_length,
        "expected_note_count": expected_note_count,
        "expected_notes": expected_notes,
        "expected_note_digest": expected_note_digest,
        "target": target,
    }


def _read_state(bridge: SupportsBridgeCall) -> Mapping[str, Any] | dict[str, Any]:
    try:
        state = bridge.call("get_state")
    except AbletonConnectionError:
        raise
    except Exception:
        return _refused(REASON_TARGET_NOT_FOUND)
    if not isinstance(state, Mapping):
        return _refused(REASON_TARGET_NOT_FOUND)
    return state


def _probe_clip(
    bridge: SupportsBridgeCall, track_index: int, clip_index: int
) -> Mapping[str, Any] | None | dict[str, Any]:
    try:
        payload = bridge.call(
            "get_midi_clip_notes", track_index=track_index, clip_index=clip_index
        )
    except AbletonConnectionError:
        raise
    except Exception as exc:
        message = str(exc)
        if any(marker in message for marker in _EMPTY_SLOT_ERRORS):
            return None
        return _refused(REASON_TARGET_NOT_FOUND)
    if not isinstance(payload, Mapping):
        return _refused(REASON_TARGET_NOT_FOUND)
    return payload


def _postcondition_holds(after: Mapping[str, Any], parsed: Mapping[str, Any]) -> bool:
    if after.get("slot_state") != SLOT_EXISTING:
        return False
    if after.get("truncated"):
        return False
    if after.get("clip") != parsed["name"]:
        return False
    if not _values_equivalent(
        after.get("length_beats"), parsed["length_beats"], _LENGTH_TOLERANCE
    ):
        return False
    return notes_equivalent(after.get("notes") or [], parsed["notes"])


def _writable_notes(notes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "pitch": int(note["pitch"]),
            "start_time": float(note["start_time"]),
            "duration": float(note["duration"]),
            "velocity": int(note["velocity"]),
        }
        for note in notes
    ]


def _lookup_track(
    state: Mapping[str, Any], track_index: int
) -> Mapping[str, Any] | None:
    tracks = state.get("tracks")
    if not isinstance(tracks, list) or track_index >= len(tracks):
        return None
    track = tracks[track_index]
    if not isinstance(track, Mapping):
        return None
    return track


def repair_live_session_midi_clip(
    bridge: SupportsBridgeCall, request: Mapping[str, Any]
) -> dict[str, Any]:
    """Read Live, maybe create one empty-slot MIDI clip, read back, return a result.

    ``request`` is a mapping (MCP arguments or a test dict). Failed guards return
    ``status="refused"`` and never send a mutation. Existing clips whose notes do
    not already match are refused: replacing them is not a single safe mutation.
    """

    parsed = _parse_request(request)
    if parsed.get("status") == STATUS_REFUSED:
        return parsed

    operation: str = parsed["operation"]
    track_index: int = parsed["track_index"]
    clip_index: int = parsed["clip_index"]
    target: dict[str, Any] = parsed["target"]

    state = _read_state(bridge)
    if isinstance(state, dict) and state.get("status") == STATUS_REFUSED:
        state["operation"] = operation
        state["target"] = target
        return state

    track = _lookup_track(state, track_index)
    if track is None:
        before = _state_view(
            track_index=track_index,
            track_name=None,
            clip_index=clip_index,
            slot_state=SLOT_EMPTY,
        )
        return _refused(
            REASON_TARGET_NOT_FOUND,
            operation=operation,
            target=target,
            before=before,
        )

    clip_slots = track.get("clip_slots")
    try:
        slot_count = int(clip_slots)
    except (TypeError, ValueError):
        slot_count = -1
    if slot_count >= 0 and clip_index >= slot_count:
        before = _state_view(
            track_index=track_index,
            track_name=track.get("name"),
            clip_index=clip_index,
            slot_state=SLOT_EMPTY,
        )
        return _refused(
            REASON_INVALID_INDEX,
            operation=operation,
            target=target,
            before=before,
        )

    probed = _probe_clip(bridge, track_index, clip_index)
    if isinstance(probed, dict) and probed.get("status") == STATUS_REFUSED:
        probed["operation"] = operation
        probed["target"] = target
        return probed

    if probed is None:
        before = _state_view(
            track_index=track_index,
            track_name=track.get("name"),
            clip_index=clip_index,
            slot_state=SLOT_EMPTY,
        )
    else:
        if probed.get("truncated"):
            before = _state_view(
                track_index=track_index,
                track_name=probed.get("track", track.get("name")),
                clip_index=clip_index,
                slot_state=SLOT_EXISTING,
                clip_name=probed.get("clip"),
                length_beats=probed.get("length_beats"),
                notes=probed.get("notes") if isinstance(probed.get("notes"), list) else [],
                truncated=True,
            )
            return _refused(
                REASON_UNOBSERVABLE_TARGET,
                operation=operation,
                target=target,
                before=before,
            )
        raw_notes = probed.get("notes")
        if not isinstance(raw_notes, list):
            return _refused(
                REASON_UNOBSERVABLE_TARGET,
                operation=operation,
                target=target,
            )
        before = _state_view(
            track_index=track_index,
            track_name=probed.get("track", track.get("name")),
            clip_index=clip_index,
            slot_state=SLOT_EXISTING,
            clip_name=probed.get("clip"),
            length_beats=probed.get("length_beats"),
            notes=raw_notes,
            truncated=False,
        )

    if (
        parsed["expected_track_name"] is not None
        and before.get("track") != parsed["expected_track_name"]
    ):
        return _refused(
            REASON_TRACK_IDENTITY_MISMATCH,
            operation=operation,
            target=target,
            before=before,
        )
    if before.get("slot_state") != parsed["expected_slot_state"]:
        return _refused(
            REASON_SLOT_OCCUPANCY_MISMATCH,
            operation=operation,
            target=target,
            before=before,
        )
    if parsed["expected_clip_name"] is not None and before.get("clip") != parsed["expected_clip_name"]:
        return _refused(
            REASON_CLIP_IDENTITY_MISMATCH,
            operation=operation,
            target=target,
            before=before,
        )
    if parsed["expected_clip_length"] is not None:
        if before.get("slot_state") != SLOT_EXISTING or not _values_equivalent(
            before.get("length_beats"), parsed["expected_clip_length"], _LENGTH_TOLERANCE
        ):
            return _refused(
                REASON_STATE_PRECONDITION_FAILED,
                operation=operation,
                target=target,
                before=before,
            )
    if parsed["expected_note_count"] is not None:
        if before.get("note_count") != parsed["expected_note_count"]:
            return _refused(
                REASON_STATE_PRECONDITION_FAILED,
                operation=operation,
                target=target,
                before=before,
            )
    if parsed["expected_notes"] is not None:
        if not notes_equivalent(before.get("notes") or [], parsed["expected_notes"]):
            return _refused(
                REASON_STATE_PRECONDITION_FAILED,
                operation=operation,
                target=target,
                before=before,
            )
    if parsed["expected_note_digest"] is not None:
        if before.get("note_digest") != parsed["expected_note_digest"]:
            return _refused(
                REASON_STATE_PRECONDITION_FAILED,
                operation=operation,
                target=target,
                before=before,
            )

    if _postcondition_holds(before, parsed):
        return _result(
            status=STATUS_NOOP,
            operation=operation,
            target=target,
            before=before,
            after=before,
            mutation_performed=False,
        )

    if before.get("slot_state") != SLOT_EMPTY:
        return _refused(
            REASON_UNSUPPORTED_REPAIR_SHAPE,
            operation=operation,
            target=target,
            before=before,
        )

    mutation_params = {
        "track_index": track_index,
        "clip_index": clip_index,
        "name": parsed["name"],
        "length_beats": parsed["length_beats"],
        "notes": _writable_notes(parsed["notes"]),
    }
    try:
        bridge.call(MUTATION_CREATE_MIDI_CLIP, **mutation_params)
    except AbletonConnectionError:
        raise
    except Exception as exc:
        after = _after_state(bridge, parsed, before)
        failed = _result(
            status=STATUS_FAILED,
            operation=operation,
            target=target,
            before=before,
            after=after,
            mutation_performed=True,
            reason=REASON_MUTATION_REJECTED,
        )
        failed["detail"] = str(exc)[:300]
        return failed

    after = _after_state(bridge, parsed, before)
    if after is None or not _postcondition_holds(after, parsed):
        return _result(
            status=STATUS_FAILED,
            operation=operation,
            target=target,
            before=before,
            after=after,
            mutation_performed=True,
            reason=REASON_POSTCONDITION_FAILED,
        )
    return _result(
        status=STATUS_REPAIRED,
        operation=operation,
        target=target,
        before=before,
        after=after,
        mutation_performed=True,
    )


def _after_state(
    bridge: SupportsBridgeCall,
    parsed: Mapping[str, Any],
    before: Mapping[str, Any],
) -> dict[str, Any] | None:
    probed = _probe_clip(bridge, parsed["track_index"], parsed["clip_index"])
    if isinstance(probed, dict) and probed.get("status") == STATUS_REFUSED:
        return None
    if probed is None:
        return _state_view(
            track_index=parsed["track_index"],
            track_name=before.get("track"),
            clip_index=parsed["clip_index"],
            slot_state=SLOT_EMPTY,
        )
    raw_notes = probed.get("notes") if isinstance(probed.get("notes"), list) else []
    return _state_view(
        track_index=parsed["track_index"],
        track_name=probed.get("track", before.get("track")),
        clip_index=parsed["clip_index"],
        slot_state=SLOT_EXISTING,
        clip_name=probed.get("clip"),
        length_beats=probed.get("length_beats"),
        notes=raw_notes,
        truncated=bool(probed.get("truncated")),
    )


def is_mutation_command(command: str) -> bool:
    """True for the one clip-repair write; false for reads and everything else."""

    return command in _MUTATION_COMMANDS
