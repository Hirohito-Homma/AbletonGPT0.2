from __future__ import annotations

import pytest

from abletongpt.bridge import AbletonConnectionError
from abletongpt.jobs import (
    AbletonStepExecutor,
    JobPlan,
    JobRunner,
    JobStep,
    StepExecutor,
    StepStatus,
    UnsupportedStepCommand,
)


class FakeBridge:
    """Records ``call`` invocations and returns canned Live-like responses.

    No socket, no Ableton process — enough to exercise AbletonStepExecutor's
    command mapping in isolation. Set ``raise_on`` to simulate a bridge failure.
    """

    def __init__(
        self,
        *,
        tempo: float = 124.0,
        is_playing: bool = False,
        tracks=None,
        devices=None,
    ):
        self._tempo = tempo
        self._is_playing = is_playing
        self._tracks = tracks if tracks is not None else [{"index": 0, "name": "Track 1"}]
        self.calls: list[tuple[str, dict]] = []
        self.raise_on: str | None = None
        self.create_error: Exception | None = None
        self.existing_clip: dict | None = None
        self.devices = list(devices or [])
        self.instrument_error: Exception | None = None

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if self.raise_on is not None and command == self.raise_on:
            raise RuntimeError("bridge boom: %s" % command)
        if command == "set_transport":
            self._is_playing = params["action"] == "play"
            return {"is_playing": self._is_playing}
        if command == "set_tempo":
            self._tempo = float(params["bpm"])
            return {"tempo": self._tempo}
        if command == "get_state":
            return {
                "is_playing": self._is_playing,
                "tempo": self._tempo,
                "tracks": self._tracks,
                "scenes": ["intro", "drop", "outro"],
            }
        if command == "get_track_devices":
            return {"track_index": params["track_index"], "devices": list(self.devices)}
        if command == "insert_first_available_instrument":
            candidate = params["candidates"][0]
            self.devices.append(
                {
                    "name": candidate,
                    "class_name": candidate,
                    "class_display_name": candidate,
                    "type": 1,
                }
            )
            if self.instrument_error is not None:
                raise self.instrument_error
            return {"name": candidate}
        if command == "create_midi_clip" and self.create_error is not None:
            raise self.create_error
        if command == "create_midi_clip":
            self.existing_clip = {
                "clip": params["name"],
                "length_beats": params["length_beats"],
                "truncated": False,
                "notes": list(params["notes"]),
            }
            return {"ok": True}
        if command == "get_midi_clip_notes" and self.existing_clip is not None:
            return self.existing_clip
        if command in {
            "create_track",
            "set_clip_envelope",
            "copy_session_clip_to_arrangement",
            "copy_scene_to_arrangement",
        }:
            return {"ok": True}
        raise AssertionError("unexpected bridge command: %s" % command)


# --- protocol conformance --------------------------------------------------------

def test_executor_satisfies_step_executor_protocol():
    executor = AbletonStepExecutor(FakeBridge())
    assert isinstance(executor, StepExecutor)
    assert set(executor.supported_commands) == {
        "play",
        "stop",
        "get_tempo",
        "set_tempo",
        "is_playing",
        "get_tracks",
        "create_track",
        "apply_live_instrument_selection",
        "apply_live_drum_kit",
        "create_midi_clip",
        "set_clip_send_envelope",
        "copy_session_clip_to_arrangement",
        "place_scene",
    }


# --- command mapping (MVP) -------------------------------------------------------

def test_play_and_stop_map_to_set_transport():
    bridge = FakeBridge()
    executor = AbletonStepExecutor(bridge)

    executor.execute(JobStep("00_play", "play"))
    executor.execute(JobStep("01_stop", "stop"))

    assert bridge.calls == [
        ("set_transport", {"action": "play"}),
        ("set_transport", {"action": "stop"}),
    ]


def test_set_tempo_forwards_bpm_as_float():
    bridge = FakeBridge()
    executor = AbletonStepExecutor(bridge)

    executor.execute(JobStep("00_tempo", "set_tempo", {"bpm": 128}))

    assert bridge.calls == [("set_tempo", {"bpm": 128.0})]


def test_read_commands_use_get_state():
    bridge = FakeBridge(tempo=140.0, is_playing=True, tracks=[{"index": 0}])
    executor = AbletonStepExecutor(bridge)

    for command in ("get_tempo", "is_playing", "get_tracks"):
        executor.execute(JobStep("id_%s" % command, command))

    # Each read command dispatches a get_state; none mutate.
    assert bridge.calls == [("get_state", {})] * 3


def test_kihachi_core_operations_map_to_the_existing_bridge_protocol():
    bridge = FakeBridge()
    executor = AbletonStepExecutor(bridge)
    notes = [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 90}
    ]
    envelope = [{"start": 0.0, "length": 4.0, "value": 0.42}]

    executor.execute(
        JobStep(
            "00_track",
            "create_track",
            {"track_type": "midi", "name": "KIHACHI Chords", "index": -1},
        )
    )
    executor.execute(
        JobStep(
            "01_clip",
            "create_midi_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "name": "Chords",
                "length_beats": 4,
                "notes": notes,
            },
        )
    )
    executor.execute(
        JobStep(
            "02_send",
            "set_clip_send_envelope",
            {
                "track_index": 0,
                "clip_index": 0,
                "send_index": 1,
                "steps": envelope,
            },
        )
    )
    executor.execute(
        JobStep(
            "03_copy",
            "copy_session_clip_to_arrangement",
            {
                "track_index": 0,
                "clip_index": 0,
                "destination_time_beats": 0,
                "name": "KIHACHI Chords",
            },
        )
    )

    assert bridge.calls == [
        (
            "create_track",
            {"track_type": "midi", "name": "KIHACHI Chords", "index": -1},
        ),
        (
            "create_midi_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "name": "Chords",
                "length_beats": 4.0,
                "notes": notes,
                "_timeout": 30.0,
            },
        ),
        ("get_midi_clip_notes", {"track_index": 0, "clip_index": 0}),
        (
            "set_clip_envelope",
            {
                "track_index": 0,
                "clip_index": 0,
                "send_index": 1,
                "steps": envelope,
            },
        ),
        (
            "copy_session_clip_to_arrangement",
            {
                "track_index": 0,
                "clip_index": 0,
                "destination_time_beats": 0.0,
                "name": "KIHACHI Chords",
            },
        ),
    ]


def test_place_scene_uses_scene_name_to_copy_scene_to_arrangement():
    bridge = FakeBridge()
    executor = AbletonStepExecutor(bridge)

    executor.execute(
        JobStep(
            "00_place_scene_drop",
            "place_scene",
            {
                "source_scene": "drop",
                "start_bar": 4,
                "length_bars": 8,
                "transition": "fill",
            },
        )
    )

    assert bridge.calls == [
        ("get_state", {}),
        (
            "copy_scene_to_arrangement",
            {
                "scene_index": 1,
                "destination_time_beats": 16.0,
                "track_indices": None,
                # A copy carries the source clip's length, so the requested length
                # travels as an assertion the Remote Script preflights.
                "expected_length_beats": 32.0,
            },
        ),
    ]


def test_instrument_selection_resolves_the_role_and_verifies_readback():
    bridge = FakeBridge()
    executor = AbletonStepExecutor(bridge)

    executor.execute(
        JobStep(
            "instrument",
            "apply_live_instrument_selection",
            {
                "track_index": 2,
                "role": "bass",
                "genre": "edm",
                "mood": "dark",
            },
        )
    )

    assert [command for command, _params in bridge.calls] == [
        "get_track_devices",
        "insert_first_available_instrument",
        "get_track_devices",
    ]
    insert = bridge.calls[1][1]
    assert insert["track_index"] == 2
    assert insert["candidates"][0] == "Operator"
    assert insert["index"] == -1


def test_instrument_selection_resume_accepts_one_matching_instrument():
    bridge = FakeBridge(
        devices=[
            {
                "name": "Operator",
                "class_name": "Operator",
                "class_display_name": "Operator",
                "type": 1,
            }
        ]
    )

    AbletonStepExecutor(bridge).execute(
        JobStep(
            "instrument",
            "apply_live_instrument_selection",
            {
                "track_index": 2,
                "role": "bass",
                "genre": "edm",
                "mood": "dark",
            },
        )
    )

    assert bridge.calls == [("get_track_devices", {"track_index": 2})]


def test_instrument_selection_refuses_to_replace_a_different_instrument():
    bridge = FakeBridge(
        devices=[
            {
                "name": "Electric",
                "class_name": "Electric",
                "class_display_name": "Electric",
                "type": 1,
            }
        ]
    )

    with pytest.raises(ValueError, match="different instrument"):
        AbletonStepExecutor(bridge).execute(
            JobStep(
                "instrument",
                "apply_live_instrument_selection",
                {
                    "track_index": 2,
                    "role": "bass",
                    "genre": "edm",
                    "mood": "dark",
                },
            )
        )

    assert bridge.calls == [("get_track_devices", {"track_index": 2})]


def test_instrument_selection_reconciles_an_ambiguous_success():
    bridge = FakeBridge()
    bridge.instrument_error = AbletonConnectionError("response timed out")

    AbletonStepExecutor(bridge).execute(
        JobStep(
            "instrument",
            "apply_live_instrument_selection",
            {
                "track_index": 2,
                "role": "bass",
                "genre": "edm",
                "mood": "dark",
            },
        )
    )

    assert [command for command, _params in bridge.calls] == [
        "get_track_devices",
        "insert_first_available_instrument",
        "get_track_devices",
    ]


@pytest.mark.parametrize(
    ("command", "params", "message"),
    [
        ("create_track", {"track_type": "return"}, "track_type"),
        (
            "apply_live_instrument_selection",
            {
                "track_index": 0,
                "role": "guitar",
                "genre": "edm",
                "mood": "dark",
            },
            "unsupported instrument role",
        ),
        (
            "create_midi_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "name": "bad",
                "length_beats": 4,
                "notes": [{"pitch": 128, "start_time": 0, "duration": 1}],
            },
            "pitch",
        ),
        (
            "create_midi_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "name": "duplicates",
                "length_beats": 4,
                "notes": [
                    {"pitch": 60, "start_time": 0, "duration": 1},
                    {"pitch": 60, "start_time": 0, "duration": 0.5},
                ],
            },
            "Live would merge",
        ),
        (
            "set_clip_send_envelope",
            {
                "track_index": 0,
                "clip_index": 0,
                "send_index": 1,
                "steps": [{"start": 0, "length": 4, "value": 1.1}],
            },
            "between 0.0 and 1.0",
        ),
        (
            "copy_session_clip_to_arrangement",
            {"track_index": 0, "clip_index": 0, "destination_time_beats": -1},
            "outside",
        ),
    ],
)
def test_kihachi_core_operations_validate_before_call(command, params, message):
    bridge = FakeBridge()
    executor = AbletonStepExecutor(bridge)

    with pytest.raises(ValueError, match=message):
        executor.execute(JobStep("bad", command, params))

    assert bridge.calls == []


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("target clip slot is not empty"),
        AbletonConnectionError("response timed out"),
    ],
)
def test_create_midi_clip_reconciles_an_ambiguous_success_by_full_readback(error):
    notes = [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 90},
        {"pitch": 64, "start_time": 1.0, "duration": 1.0, "velocity": 88},
    ]
    bridge = FakeBridge()
    bridge.create_error = error
    bridge.existing_clip = {
        "clip": "Chords",
        "length_beats": 4.0,
        "truncated": False,
        # Live may reorder notes and move beat values by sub-microbeat amounts.
        "notes": [
            {"pitch": 64, "start_time": 1.00000005, "duration": 1.0, "velocity": 88},
            {"pitch": 60, "start_time": 0.0, "duration": 1.00000005, "velocity": 90},
        ],
    }
    params = {
        "track_index": 2,
        "clip_index": 0,
        "name": "Chords",
        "length_beats": 4,
        "notes": notes,
    }

    AbletonStepExecutor(bridge).execute(JobStep("clip", "create_midi_clip", params))

    assert [command for command, _params in bridge.calls] == [
        "create_midi_clip",
        "get_midi_clip_notes",
    ]


def test_create_midi_clip_refuses_an_occupied_slot_with_different_notes():
    bridge = FakeBridge()
    bridge.create_error = RuntimeError("target clip slot is not empty")
    bridge.existing_clip = {
        "clip": "Chords",
        "length_beats": 4.0,
        "truncated": False,
        "notes": [{"pitch": 61, "start_time": 0.0, "duration": 1.0, "velocity": 90}],
    }
    params = {
        "track_index": 2,
        "clip_index": 0,
        "name": "Chords",
        "length_beats": 4,
        "notes": [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 90}],
    }

    with pytest.raises(RuntimeError, match="not empty"):
        AbletonStepExecutor(bridge).execute(
            JobStep("clip", "create_midi_clip", params)
        )


# --- failure handling ------------------------------------------------------------

def test_unsupported_command_raises_unsupported_step_command():
    bridge = FakeBridge()
    executor = AbletonStepExecutor(bridge)

    with pytest.raises(UnsupportedStepCommand):
        executor.execute(JobStep("00_bad", "make_me_a_hit_song"))
    # Nothing was sent to the bridge for an unknown command.
    assert bridge.calls == []


def test_missing_required_param_propagates():
    executor = AbletonStepExecutor(FakeBridge())
    with pytest.raises(KeyError):
        executor.execute(JobStep("00_tempo", "set_tempo"))  # no bpm


def test_bridge_error_is_not_swallowed_by_executor():
    bridge = FakeBridge()
    bridge.raise_on = "set_transport"
    executor = AbletonStepExecutor(bridge)

    with pytest.raises(RuntimeError, match="bridge boom"):
        executor.execute(JobStep("00_play", "play"))


# --- integration with JobRunner --------------------------------------------------

def test_runner_drives_executor_end_to_end():
    bridge = FakeBridge()
    plan = JobPlan(
        name="transport_smoke",
        steps=(
            JobStep("00_tempo", "set_tempo", {"bpm": 126}),
            JobStep("01_play", "play"),
            JobStep("02_tracks", "get_tracks"),
            JobStep("03_stop", "stop"),
        ),
    )

    result = JobRunner(AbletonStepExecutor(bridge)).run(plan)

    assert result.succeeded
    assert [c[0] for c in bridge.calls] == [
        "set_tempo",
        "set_transport",
        "get_state",
        "set_transport",
    ]


def test_runner_records_unsupported_command_as_failed_not_crash():
    bridge = FakeBridge()
    plan = JobPlan(
        name="mixed",
        steps=(
            JobStep("00_play", "play"),
            JobStep("01_bad", "unsupported_op"),
            JobStep("02_stop", "stop"),
        ),
    )

    result = JobRunner(AbletonStepExecutor(bridge)).run(plan)

    assert not result.succeeded
    statuses = {r.step_id: r.status for r in result.results}
    assert statuses["00_play"] is StepStatus.SUCCEEDED
    assert statuses["01_bad"] is StepStatus.FAILED
    # Default stop_on_error halts the run; the trailing step stays PENDING.
    assert statuses["02_stop"] is StepStatus.PENDING

    failed = next(r for r in result.results if r.step_id == "01_bad")
    assert failed.error is not None
    assert "unsupported_op" in failed.error


def test_bridge_failure_becomes_failed_step_result():
    bridge = FakeBridge()
    bridge.raise_on = "set_tempo"
    plan = JobPlan(name="one", steps=(JobStep("00_tempo", "set_tempo", {"bpm": 130}),))

    result = JobRunner(AbletonStepExecutor(bridge)).run(plan)

    assert not result.succeeded
    assert result.results[0].status is StepStatus.FAILED
    assert "bridge boom" in result.results[0].error
