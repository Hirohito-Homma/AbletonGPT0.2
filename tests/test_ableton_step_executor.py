from __future__ import annotations

import pytest

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

    def __init__(self, *, tempo: float = 124.0, is_playing: bool = False, tracks=None):
        self._tempo = tempo
        self._is_playing = is_playing
        self._tracks = tracks if tracks is not None else [{"index": 0, "name": "Track 1"}]
        self.calls: list[tuple[str, dict]] = []
        self.raise_on: str | None = None

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
            }
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
