"""Guarded selective Session MIDI clip repair: one approved Live mutation.

A fake bridge stands in for Ableton. Tests prove call ordering and that a
refusal or no-op never writes, a success writes exactly once, and a failed
readback never retries.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from abletongpt.bridge import AbletonConnectionError
from abletongpt.clip_repair import (
    REASON_CLIP_IDENTITY_MISMATCH,
    REASON_INVALID_INDEX,
    REASON_MALFORMED_NOTES,
    REASON_POSTCONDITION_FAILED,
    REASON_SLOT_OCCUPANCY_MISMATCH,
    REASON_STATE_PRECONDITION_FAILED,
    REASON_TRACK_IDENTITY_MISMATCH,
    REASON_UNSUPPORTED_REPAIR_SHAPE,
    SLOT_EMPTY,
    SLOT_EXISTING,
    STATUS_FAILED,
    STATUS_NOOP,
    STATUS_REFUSED,
    STATUS_REPAIRED,
    is_mutation_command,
    notes_digest,
    notes_equivalent,
    repair_live_session_midi_clip,
)
from abletongpt.device_repair import (
    STATUS_REPAIRED as DEVICE_STATUS_REPAIRED,
    repair_live_device,
)
from abletongpt import server
from test_device_repair import FakeDeviceBridge, _request as _device_request


def _note(
    pitch: int = 60,
    start_time: float = 0.0,
    duration: float = 1.0,
    velocity: int = 100,
    probability: float = 1.0,
) -> dict[str, Any]:
    return {
        "pitch": pitch,
        "start_time": start_time,
        "duration": duration,
        "velocity": velocity,
        "probability": probability,
    }


def _clip(
    *,
    track_index: int = 1,
    track: str = "Bass",
    clip_index: int = 0,
    name: str = "Bass Loop",
    length_beats: float = 4.0,
    notes: list[dict[str, Any]] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    observed = notes if notes is not None else [_note()]
    return {
        "track_index": track_index,
        "track": track,
        "clip_index": clip_index,
        "clip": name,
        "length_beats": length_beats,
        "tempo": 120.0,
        "time_signature": [4, 4],
        "notes": copy.deepcopy(observed),
        "note_count": len(observed),
        "truncated": truncated,
    }


def _state(
    *,
    track_index: int = 1,
    track: str = "Bass",
    clip_slots: int = 8,
    extra_tracks: int = 0,
) -> dict[str, Any]:
    tracks = [{"index": 0, "name": "Drums", "clip_slots": clip_slots}]
    tracks.append({"index": track_index, "name": track, "clip_slots": clip_slots})
    for offset in range(extra_tracks):
        tracks.append(
            {"index": track_index + 1 + offset, "name": "Extra", "clip_slots": clip_slots}
        )
    return {"tempo": 120.0, "scene_count": clip_slots, "tracks": tracks}


class FakeClipBridge:
    """Live stand-in that records every call and optionally applies one create."""

    def __init__(
        self,
        *,
        state: dict[str, Any] | None = None,
        clip: dict[str, Any] | None = None,
        apply_mutation: bool = True,
        mutation_error: Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.state = copy.deepcopy(state if state is not None else _state())
        self.clip = copy.deepcopy(clip)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.apply_mutation = apply_mutation
        self.mutation_error = mutation_error
        self.read_error = read_error

    def call(self, command: str, **params: Any) -> Any:
        self.calls.append((command, dict(params)))
        if command == "get_state":
            if self.read_error is not None:
                raise self.read_error
            return copy.deepcopy(self.state)
        if command == "get_midi_clip_notes":
            if self.clip is None:
                raise RuntimeError("target clip slot does not contain a MIDI clip")
            return copy.deepcopy(self.clip)
        if command == "create_midi_clip":
            if self.mutation_error is not None:
                raise self.mutation_error
            if self.clip is not None:
                raise RuntimeError("target clip slot is not empty")
            if self.apply_mutation:
                self.clip = _clip(
                    track_index=params["track_index"],
                    track=self._track_name(params["track_index"]),
                    clip_index=params["clip_index"],
                    name=params["name"],
                    length_beats=params["length_beats"],
                    notes=[
                        _note(
                            pitch=int(note["pitch"]),
                            start_time=float(note["start_time"]),
                            duration=float(note["duration"]),
                            velocity=int(note.get("velocity", 100)),
                        )
                        for note in params["notes"]
                    ],
                )
            return {
                "track": self._track_name(params["track_index"]),
                "clip_index": params["clip_index"],
                "clip": params["name"],
                "length_beats": params["length_beats"],
                "note_count": len(params["notes"]),
            }
        raise AssertionError("unexpected command: %s" % command)

    def _track_name(self, track_index: int) -> str:
        tracks = self.state["tracks"]
        return tracks[track_index]["name"]

    def mutations(self) -> list[tuple[str, dict[str, Any]]]:
        return [(command, params) for command, params in self.calls if is_mutation_command(command)]

    def reads(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            (command, params)
            for command, params in self.calls
            if command in {"get_state", "get_midi_clip_notes"}
        ]


def _desired_notes() -> list[dict[str, Any]]:
    return [_note(60, 0.0, 1.0, 100), _note(64, 1.0, 1.0, 90)]


def _request(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "track_index": 1,
        "clip_index": 0,
        "name": "Bass Loop",
        "length_beats": 4.0,
        "notes": _desired_notes(),
        "expected_slot_state": SLOT_EMPTY,
        "expected_track_name": "Bass",
    }
    base.update(overrides)
    return base


def test_already_correct_clip_is_noop_with_zero_mutation():
    existing = _clip(notes=_desired_notes())
    bridge = FakeClipBridge(clip=existing)
    result = repair_live_session_midi_clip(
        bridge,
        _request(
            expected_slot_state=SLOT_EXISTING,
            expected_clip_name="Bass Loop",
            expected_clip_length=4.0,
            expected_note_count=2,
            expected_notes=list(reversed(_desired_notes())),
        ),
    )

    assert result["status"] == STATUS_NOOP
    assert result["mutation_performed"] is False
    assert bridge.mutations() == []
    assert [command for command, _ in bridge.calls] == ["get_state", "get_midi_clip_notes"]


def test_supported_empty_slot_repair_performs_exactly_one_mutation():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(bridge, _request())

    assert result["status"] == STATUS_REPAIRED
    assert result["mutation_performed"] is True
    assert result["operation"] == "create_midi_clip"
    assert result["before"]["slot_state"] == SLOT_EMPTY
    assert result["after"]["clip"] == "Bass Loop"
    assert result["after"]["note_count"] == 2
    assert len(bridge.mutations()) == 1
    assert bridge.mutations()[0][0] == "create_midi_clip"


def test_read_happens_before_mutation():
    bridge = FakeClipBridge()
    repair_live_session_midi_clip(bridge, _request())

    commands = [command for command, _ in bridge.calls]
    assert commands[0] == "get_state"
    assert "get_midi_clip_notes" in commands
    assert commands.index("get_state") < commands.index("create_midi_clip")
    assert commands.index("get_midi_clip_notes") < commands.index("create_midi_clip")


def test_postcondition_read_happens_after_mutation():
    bridge = FakeClipBridge()
    repair_live_session_midi_clip(bridge, _request())

    commands = [command for command, _ in bridge.calls]
    assert commands[-1] == "get_midi_clip_notes"
    assert commands.index("create_midi_clip") < len(commands) - 1
    assert commands.count("get_midi_clip_notes") == 2
    assert commands.count("create_midi_clip") == 1


def test_postcondition_proven_is_repaired():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(bridge, _request())

    assert result["status"] == STATUS_REPAIRED
    assert notes_equivalent(result["after"]["notes"], _desired_notes())
    assert result["after"]["note_digest"] == notes_digest(_desired_notes(), 4.0)


def test_failed_readback_is_failed_and_does_not_retry():
    bridge = FakeClipBridge(apply_mutation=False)
    result = repair_live_session_midi_clip(bridge, _request())

    assert result["status"] == STATUS_FAILED
    assert result["reason"] == REASON_POSTCONDITION_FAILED
    assert result["mutation_performed"] is True
    assert len(bridge.mutations()) == 1
    assert [command for command, _ in bridge.calls] == [
        "get_state",
        "get_midi_clip_notes",
        "create_midi_clip",
        "get_midi_clip_notes",
    ]


def test_wrong_track_identity_refuses_without_mutation():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(bridge, _request(expected_track_name="Pads"))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_TRACK_IDENTITY_MISMATCH
    assert result["mutation_performed"] is False
    assert bridge.mutations() == []


def test_wrong_clip_identity_refuses_without_mutation():
    bridge = FakeClipBridge(clip=_clip(name="Old Loop", notes=_desired_notes()))
    result = repair_live_session_midi_clip(
        bridge,
        _request(
            expected_slot_state=SLOT_EXISTING,
            expected_clip_name="Bass Loop",
        ),
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_CLIP_IDENTITY_MISMATCH
    assert bridge.mutations() == []


def test_stale_notes_precondition_refuses_without_mutation():
    current = [_note(60, 0.0, 1.0, 100)]
    bridge = FakeClipBridge(clip=_clip(notes=current))
    result = repair_live_session_midi_clip(
        bridge,
        _request(
            expected_slot_state=SLOT_EXISTING,
            expected_clip_name="Bass Loop",
            expected_notes=_desired_notes(),
        ),
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_STATE_PRECONDITION_FAILED
    assert bridge.mutations() == []


def test_stale_note_digest_refuses_without_mutation():
    bridge = FakeClipBridge(clip=_clip(notes=_desired_notes()))
    result = repair_live_session_midi_clip(
        bridge,
        _request(
            expected_slot_state=SLOT_EXISTING,
            expected_note_digest="0" * 64,
        ),
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_STATE_PRECONDITION_FAILED
    assert bridge.mutations() == []


def test_occupied_slot_when_empty_expected_refuses_without_mutation():
    bridge = FakeClipBridge(clip=_clip())
    result = repair_live_session_midi_clip(bridge, _request(expected_slot_state=SLOT_EMPTY))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_SLOT_OCCUPANCY_MISMATCH
    assert result["mutation_performed"] is False
    assert bridge.mutations() == []


def test_empty_slot_when_existing_expected_refuses_without_mutation():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(
        bridge, _request(expected_slot_state=SLOT_EXISTING)
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_SLOT_OCCUPANCY_MISMATCH
    assert bridge.mutations() == []


def test_malformed_notes_refuse_before_live_write():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(
        bridge,
        _request(notes=[{"pitch": 60, "start_time": 0.0}]),
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_MALFORMED_NOTES
    assert result["mutation_performed"] is False
    assert bridge.calls == []


@pytest.mark.parametrize(
    "notes",
    [
        "not-a-list",
        [{"pitch": True, "start_time": 0.0, "duration": 1.0}],
        [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "extra": 1}],
        [
            {"pitch": 60, "start_time": 0.0, "duration": 1.0},
            {"pitch": 60, "start_time": 0.0, "duration": 0.5},
        ],
        [{"pitch": 60, "start_time": 4.0, "duration": 1.0}],
        [{"pitch": 128, "start_time": 0.0, "duration": 1.0}],
    ],
)
def test_malformed_note_shapes_refuse_before_live(notes):
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(bridge, _request(notes=notes))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_MALFORMED_NOTES
    assert bridge.calls == []


@pytest.mark.parametrize("track_index", [-1, True, 1.5, "0"])
def test_invalid_track_index_causes_zero_writes(track_index):
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(bridge, _request(track_index=track_index))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_INVALID_INDEX
    assert bridge.calls == []
    assert bridge.mutations() == []


@pytest.mark.parametrize("clip_index", [-1, True, 1.5, "0"])
def test_invalid_clip_index_causes_zero_writes(clip_index):
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(bridge, _request(clip_index=clip_index))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_INVALID_INDEX
    assert bridge.calls == []


def test_clip_index_outside_scene_count_refuses_after_state_read():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(bridge, _request(clip_index=99))

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_INVALID_INDEX
    assert bridge.mutations() == []
    assert [command for command, _ in bridge.calls] == ["get_state"]


def test_unsupported_existing_clip_rewrite_refuses_without_mutation():
    bridge = FakeClipBridge(clip=_clip(notes=[_note(72, 0.0, 1.0, 80)]))
    result = repair_live_session_midi_clip(
        bridge,
        _request(
            expected_slot_state=SLOT_EXISTING,
            expected_clip_name="Bass Loop",
            expected_notes=[_note(72, 0.0, 1.0, 80)],
        ),
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_UNSUPPORTED_REPAIR_SHAPE
    assert result["mutation_performed"] is False
    assert bridge.mutations() == []


def test_apply_expression_operation_is_unsupported_before_live():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(
        bridge, _request(operation="apply_expression_to_clip")
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_UNSUPPORTED_REPAIR_SHAPE
    assert bridge.calls == []


def test_muted_desired_notes_are_unsupported_before_live():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(
        bridge,
        _request(notes=[{**_note(), "mute": True}]),
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_UNSUPPORTED_REPAIR_SHAPE
    assert bridge.calls == []


def test_non_default_probability_is_unsupported_before_live():
    bridge = FakeClipBridge()
    result = repair_live_session_midi_clip(
        bridge,
        _request(notes=[{**_note(), "probability": 0.5}]),
    )

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == REASON_UNSUPPORTED_REPAIR_SHAPE
    assert bridge.calls == []


def test_mutation_count_never_exceeds_one():
    bridge = FakeClipBridge()
    repair_live_session_midi_clip(bridge, _request())
    assert len(bridge.mutations()) == 1

    occupied = FakeClipBridge(clip=_clip(notes=_desired_notes()))
    repair_live_session_midi_clip(
        occupied, _request(expected_slot_state=SLOT_EXISTING)
    )
    assert occupied.mutations() == []

    failed = FakeClipBridge(apply_mutation=False)
    repair_live_session_midi_clip(failed, _request())
    assert len(failed.mutations()) == 1


def test_ordering_only_differences_do_not_produce_false_mismatch():
    reversed_notes = list(reversed(_desired_notes()))
    bridge = FakeClipBridge(clip=_clip(notes=reversed_notes))
    result = repair_live_session_midi_clip(
        bridge,
        _request(
            expected_slot_state=SLOT_EXISTING,
            expected_clip_name="Bass Loop",
            expected_notes=_desired_notes(),
            expected_note_digest=notes_digest(_desired_notes(), 4.0),
        ),
    )

    assert result["status"] == STATUS_NOOP
    assert notes_equivalent(reversed_notes, _desired_notes())
    assert notes_digest(reversed_notes, 4.0) == notes_digest(_desired_notes(), 4.0)
    assert bridge.mutations() == []


def test_created_clip_notes_match_even_when_live_returns_a_different_order():
    class ReorderingBridge(FakeClipBridge):
        def call(self, command: str, **params: Any) -> Any:
            result = super().call(command, **params)
            if command == "create_midi_clip" and self.clip is not None:
                self.clip["notes"] = list(reversed(self.clip["notes"]))
            return result

    bridge = ReorderingBridge()
    result = repair_live_session_midi_clip(bridge, _request())

    assert result["status"] == STATUS_REPAIRED
    assert notes_equivalent(result["after"]["notes"], _desired_notes())


def test_bridge_connection_failure_is_fail_closed():
    bridge = FakeClipBridge(read_error=AbletonConnectionError("Ableton Liveに接続できません。"))
    with pytest.raises(AbletonConnectionError):
        repair_live_session_midi_clip(bridge, _request())
    assert bridge.mutations() == []
    assert [command for command, _ in bridge.calls] == ["get_state"]


def test_unexpected_read_exception_is_refused_without_mutation():
    bridge = FakeClipBridge(read_error=RuntimeError("socket exploded"))
    result = repair_live_session_midi_clip(bridge, _request())

    assert result["status"] == STATUS_REFUSED
    assert result["mutation_performed"] is False
    assert bridge.mutations() == []


def test_mutation_rejection_is_failed_and_does_not_retry():
    bridge = FakeClipBridge(mutation_error=RuntimeError("target clip slot is not empty"))
    result = repair_live_session_midi_clip(bridge, _request())

    assert result["status"] == STATUS_FAILED
    assert result["reason"] == "mutation_rejected"
    assert result["mutation_performed"] is True
    assert len(bridge.mutations()) == 1
    assert [command for command, _ in bridge.calls] == [
        "get_state",
        "get_midi_clip_notes",
        "create_midi_clip",
        "get_midi_clip_notes",
    ]


def test_existing_repair_live_device_behavior_remains_unchanged():
    bridge = FakeDeviceBridge()
    result = repair_live_device(bridge, _device_request())

    assert result["status"] == DEVICE_STATUS_REPAIRED
    assert result["operation"] == "set_device_parameter"
    assert len(bridge.mutations()) == 1
    assert [command for command, _ in bridge.calls] == [
        "get_track_devices",
        "set_device_parameter",
        "get_track_devices",
    ]


def test_server_tool_forwards_to_the_guarded_engine(monkeypatch):
    bridge = FakeClipBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    result = server.repair_live_session_midi_clip(
        track_index=1,
        clip_index=0,
        name="Bass Loop",
        length_beats=4.0,
        notes=_desired_notes(),
        expected_slot_state=SLOT_EMPTY,
        expected_track_name="Bass",
    )

    assert result["status"] == STATUS_REPAIRED
    assert len(bridge.mutations()) == 1


def test_capabilities_name_guarded_session_midi_clip_repair():
    capabilities = server.get_abletongpt_capabilities()
    assert any("Session MIDI clip repair" in feature for feature in capabilities["features"])
    assert any("candidate repairable clip is not automatically safe" in rule for rule in capabilities["safety"])
    assert any("guarded selective device repair" in feature for feature in capabilities["features"])


def test_missing_slot_state_refuses_before_live():
    bridge = FakeClipBridge()
    request = _request()
    del request["expected_slot_state"]
    result = repair_live_session_midi_clip(bridge, request)

    assert result["status"] == STATUS_REFUSED
    assert result["reason"] == "missing_field"
    assert bridge.calls == []


def test_python_hash_is_not_used_for_note_identity():
    first = notes_digest(_desired_notes(), 4.0)
    second = notes_digest(list(reversed(_desired_notes())), 4.0)
    assert first == second
    assert len(first) == 64
    int(first, 16)
