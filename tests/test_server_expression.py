"""Tests for the ``plan_expression`` MCP tool.

``plan_expression`` reads an existing MIDI clip from Live (via the bridge) and runs the
deterministic ``build_expression_plan`` engine. It is read-only: the tool must never
call a mutating bridge command. A fake bridge stands in for Ableton -- no socket, no
Live process.
"""

from __future__ import annotations

import pytest

from abletongpt import server


_CLIP_RESPONSE = {
    "track_index": 0,
    "track": "Keys",
    "clip_index": 0,
    "clip": "Chords",
    "length_beats": 8.0,
    "tempo": 120.0,
    "time_signature": [4, 4],
    "notes": [
        {"pitch": 60, "start_time": 0.0, "duration": 0.5, "velocity": 80, "probability": 1.0},
        {"pitch": 62, "start_time": 0.5, "duration": 0.5, "velocity": 80, "probability": 1.0},
        {"pitch": 64, "start_time": 1.0, "duration": 0.5, "velocity": 80, "probability": 1.0},
    ],
    "note_count": 3,
    "truncated": False,
}


class FakeBridge:
    """Returns a canned clip for ``get_midi_clip_notes`` and records every call."""

    def __init__(self, clip=_CLIP_RESPONSE):
        self._clip = clip
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            return dict(self._clip)
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_expression_is_read_only(fake_bridge):
    plan = server.plan_expression(0, 0, accent=0.5, swing=0.4)

    assert plan["read_only"] is True
    # Only the read command was issued -- no mutation reached the bridge.
    assert [command for command, _ in fake_bridge.calls] == ["get_midi_clip_notes"]


def test_plan_expression_forwards_clip_target(fake_bridge):
    server.plan_expression(2, 3)

    command, params = fake_bridge.calls[0]
    assert command == "get_midi_clip_notes"
    assert params == {"track_index": 2, "clip_index": 3}


def test_plan_expression_applies_accent_from_live_clip(fake_bridge):
    plan = server.plan_expression(0, 0, accent=1.0)

    by_start = {note["start_time"]: note for note in plan["notes"]}
    assert by_start[0.0]["velocity"] > 80  # downbeat boosted
    assert by_start[0.5]["velocity"] < 80  # off-beat softened


def test_plan_expression_includes_requested_automation(fake_bridge):
    plan = server.plan_expression(0, 0, automation_shape="arch", automation_cc=11)

    assert plan["diff"]["automation_envelopes"] == 1
    assert plan["automation"][0]["controller"] == 11
    assert plan["apply_contract"]["writes_automation_envelopes"] is True


def test_plan_expression_rejects_unknown_automation_shape(fake_bridge):
    with pytest.raises(ValueError):
        server.plan_expression(0, 0, automation_shape="zigzag")
    # Rejected before any clip was read.
    assert fake_bridge.calls == []


def test_plan_expression_is_deterministic(fake_bridge):
    first = server.plan_expression(0, 0, humanize=0.8, seed=5)
    second = server.plan_expression(0, 0, humanize=0.8, seed=5)

    assert first["notes"] == second["notes"]
