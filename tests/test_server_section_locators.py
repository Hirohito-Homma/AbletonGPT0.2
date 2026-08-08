"""Tests for the section-driven Arrangement-locator tools.

``create_arrangement_locators_from_structure`` has to *detect* sections in a
render, so it needs NumPy and a tempo. When the arrangement is already known --
composed rather than analysed -- neither is needed: bar numbers become beats
through the time signature alone.

The plan tool must never touch the bridge, and the create tool must validate
before it does. A fake bridge stands in for Ableton -- no socket, no Live.
"""

from __future__ import annotations

import pytest

from abletongpt import server


_SECTIONS = [
    {"name": "minimal_intro", "start_bar": 1, "length_bars": 16},
    {"name": "psychedelic_drop", "start_bar": 17, "length_bars": 16},
    {"name": "outro", "start_bar": 33, "length_bars": 8},
]


class FakeBridge:
    """A Live that moves its transport only on the *next* command.

    This mirrors the measured behaviour: ``jump_transport`` schedules the move
    and the new position is visible to the following command, never to the one
    that issued it.
    """

    def __init__(self, response=None, transport_is_stuck=False):
        self._response = response
        self.transport_is_stuck = transport_is_stuck
        self._time = 0.0
        self._pending = None
        self.cues: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if self._pending is not None:
            self._time = self._pending
            self._pending = None
        if command == "get_transport_state":
            if self._response is not None:
                return dict(self._response)
            return {
                "current_song_time": self._time,
                "cue_points": list(self.cues),
                "cue_count": len(self.cues),
                "read_only": True,
            }
        if command == "jump_transport":
            if not self.transport_is_stuck:
                self._pending = float(params["time"])
            return {"requested": params["time"], "before": self._time}
        if command == "toggle_cue_at_playhead":
            expected = float(params["expected_time"])
            if abs(self._time - expected) > 1e-4:
                return {"created": False, "time": self._time, "reason": "wrong position"}
            self.cues.append({"time": expected, "name": params.get("name", "")})
            return {"created": True, "time": expected, "name": params.get("name", "")}
        raise AssertionError("unexpected command: %s" % command)


def test_plan_is_read_only_and_needs_no_tempo(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    plan = server.plan_arrangement_locators_from_sections(_SECTIONS)

    assert bridge.calls == []
    assert plan["count"] == 3
    assert [locator["time_beats"] for locator in plan["locators"]] == [0.0, 64.0, 128.0]


def test_create_places_every_locator_at_its_planned_beat(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    result = server.create_arrangement_locators_from_sections(_SECTIONS)

    assert result["created_count"] == 3
    assert [cue["time"] for cue in bridge.cues] == [0.0, 64.0, 128.0]
    assert [cue["name"] for cue in bridge.cues] == [
        "1 minimal_intro",
        "2 psychedelic_drop",
        "3 outro",
    ]
    assert result["source"] == "explicit_sections"
    assert result["planned_count"] == 3


def test_the_move_and_the_toggle_never_share_a_command(monkeypatch):
    """The bug this fixes: Live applies a transport move on a later tick."""
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    server.create_arrangement_locators_from_sections(_SECTIONS)

    commands = [command for command, _ in bridge.calls]
    for index, command in enumerate(commands):
        if command == "toggle_cue_at_playhead":
            # a confirmation read always sits between the move and the toggle
            assert commands[index - 1] == "get_transport_state"
            assert commands[index - 2] == "jump_transport"


def test_a_stuck_transport_places_nothing_and_deletes_nothing(monkeypatch):
    bridge = FakeBridge(transport_is_stuck=True)
    # park it away from every planned beat so nothing matches by coincidence
    bridge._time = 999.0
    monkeypatch.setattr(server, "bridge", bridge)

    result = server.create_arrangement_locators_from_sections(_SECTIONS)

    assert result["created_count"] == 0
    assert result["skipped_count"] == 3
    assert bridge.cues == []
    assert "toggle_cue_at_playhead" not in [command for command, _ in bridge.calls]


def test_the_transport_is_put_back_where_it_was(monkeypatch):
    bridge = FakeBridge()
    bridge._time = 512.0
    monkeypatch.setattr(server, "bridge", bridge)

    server.create_arrangement_locators_from_sections(_SECTIONS)

    last_jump = [params for command, params in bridge.calls if command == "jump_transport"][-1]
    assert last_jump["time"] == 512.0


def test_create_can_close_the_song_with_an_end_locator(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    server.create_arrangement_locators_from_sections(_SECTIONS, include_end=True)

    assert bridge.cues[-1] == {"time": 160.0, "name": "End"}


def test_create_honours_the_time_signature(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    server.create_arrangement_locators_from_sections(_SECTIONS, time_signature="3/4")

    assert [cue["time"] for cue in bridge.cues] == [0.0, 48.0, 96.0]


@pytest.mark.parametrize(
    "sections",
    [
        [],
        [{"name": "a", "start_bar": 0}],
        [{"name": "a"}],
        [{"name": "a", "start_bar": 9}, {"name": "b", "start_bar": 5}],
        [{"name": "a", "start_bar": 1}, {"name": "b", "start_bar": 1}],
    ],
)
def test_bad_sections_are_refused_before_the_bridge_is_touched(monkeypatch, sections):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    with pytest.raises(ValueError):
        server.create_arrangement_locators_from_sections(sections)

    assert bridge.calls == []


def test_the_tool_never_deletes(monkeypatch):
    """Placement is additive; no delete-capable command is ever issued."""
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    server.create_arrangement_locators_from_sections(_SECTIONS)

    used = {command for command, _ in bridge.calls}
    assert used <= {"get_transport_state", "jump_transport", "toggle_cue_at_playhead"}


def test_transport_state_is_read_only(monkeypatch):
    """The diagnostic must observe Live, never change it."""
    snapshot = {
        "current_song_time": 512.0,
        "start_time": 0.0,
        "song_length": 544.0,
        "is_playing": False,
        "loop": False,
        "cue_points": [{"time": 0.0, "name": "1 intro"}],
        "cue_count": 1,
        "read_only": True,
    }
    bridge = FakeBridge(snapshot)
    monkeypatch.setattr(server, "bridge", bridge)

    result = server.get_transport_state()

    assert [command for command, _ in bridge.calls] == ["get_transport_state"]
    assert bridge.calls[0][1] == {}
    assert result["current_song_time"] == 512.0
    assert result["read_only"] is True


class _EnvelopeBridge(FakeBridge):
    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "set_clip_envelope":
            return {"step_count": len(params["steps"]), "parameter": "Dry Wet"}
        return super().call(command, **params)


def test_envelope_steps_are_validated_before_the_bridge_is_touched(monkeypatch):
    bridge = _EnvelopeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    bad = [
        [],
        [{"start": -1.0, "length": 4.0, "value": 0.3}],
        [{"start": 0.0, "length": 0.0, "value": 0.3}],
        [{"start": 0.0, "length": 4.0}],
        [{"start": 0.0, "length": 4.0, "value": 0.3}] * (server.MAX_ENVELOPE_STEPS + 1),
    ]
    for steps in bad:
        with pytest.raises(ValueError):
            server.set_clip_parameter_envelope(3, 0, 1, 52, steps)
    assert bridge.calls == []


def test_envelope_steps_reach_the_bridge_unchanged(monkeypatch):
    bridge = _EnvelopeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    steps = [
        {"start": 0.0, "length": 64.0, "value": 0.30},
        {"start": 320.0, "length": 64.0, "value": 1.00},
    ]

    result = server.set_clip_parameter_envelope(3, 0, 1, 52, steps)

    command, params = bridge.calls[0]
    assert command == "set_clip_envelope"
    assert params["steps"] == steps
    assert params["track_index"] == 3 and params["parameter_index"] == 52
    assert result["step_count"] == 2


def test_negative_indices_are_refused(monkeypatch):
    bridge = _EnvelopeBridge()
    monkeypatch.setattr(server, "bridge", bridge)

    with pytest.raises(ValueError):
        server.set_clip_parameter_envelope(-1, 0, 1, 52, [{"start": 0, "length": 4, "value": 0.5}])
    assert bridge.calls == []
