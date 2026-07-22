"""Tests for the plan_/create_timescale_clip MCP tools (no Live)."""

from __future__ import annotations

import copy

import pytest

from abletongpt import server


_CLIP = {
    "track_index": 0,
    "track": "Keys",
    "clip_index": 0,
    "clip": "Riff",
    "length_beats": 4.0,
    "tempo": 120.0,
    "time_signature": [4, 4],
    "notes": [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100, "probability": 1.0},
        {"pitch": 64, "start_time": 2.0, "duration": 1.0, "velocity": 100, "probability": 1.0},
    ],
    "note_count": 2,
    "truncated": False,
}


class FakeBridge:
    def __init__(self, occupied=frozenset()):
        self._occupied = set(occupied)
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            return copy.deepcopy(_CLIP)
        if command == "create_midi_clip":
            if (params["track_index"], params["clip_index"]) in self._occupied:
                raise ValueError("target clip slot is not empty")
            return {"clip_index": params["clip_index"], "length_beats": params["length_beats"], "note_count": len(params["notes"])}
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_half_time_is_read_only(fake_bridge):
    plan = server.plan_timescale_clip(0, 0, mode="half")
    assert plan["read_only"] is True
    assert plan["factor"] == 2.0
    assert plan["length_beats"] == 8.0
    assert plan["mode"] == "half"
    assert [command for command, _ in fake_bridge.calls] == ["get_midi_clip_notes"]


def test_plan_double_via_explicit_factor(fake_bridge):
    plan = server.plan_timescale_clip(0, 0, factor=0.5)
    assert plan["length_beats"] == 2.0
    assert [(n["start_time"], n["duration"]) for n in plan["notes"]] == [(0.0, 0.5), (1.0, 0.5)]


def test_create_writes_scaled_clip_to_destination(fake_bridge):
    result = server.create_timescale_clip(0, 0, destination_clip_index=1, mode="half")
    commands = [command for command, _ in fake_bridge.calls]
    assert commands == ["get_midi_clip_notes", "create_midi_clip"]
    write = fake_bridge.calls[1][1]
    assert write["track_index"] == 0 and write["clip_index"] == 1
    assert write["length_beats"] == 8.0
    assert result["factor"] == 2.0


def test_create_refuses_occupied_slot(monkeypatch):
    monkeypatch.setattr(server, "bridge", FakeBridge(occupied={(0, 1)}))
    with pytest.raises(ValueError, match="not empty"):
        server.create_timescale_clip(0, 0, destination_clip_index=1, mode="double")


def test_create_guards_stale_fingerprint(fake_bridge):
    plan = server.plan_timescale_clip(0, 0, mode="double")
    server.create_timescale_clip(
        0, 0, destination_clip_index=1, mode="double", expected_source_fingerprint=plan["source_fingerprint"]
    )
    fake_bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.create_timescale_clip(
            0, 0, destination_clip_index=1, mode="double", expected_source_fingerprint="deadbeef"
        )
    assert all(command != "create_midi_clip" for command, _ in fake_bridge.calls)


def test_missing_mode_and_factor_errors(fake_bridge):
    with pytest.raises(ValueError):
        server.plan_timescale_clip(0, 0)  # neither mode nor factor
