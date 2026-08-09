"""Tests for the plan_/create_developed_arrangement MCP tools.

plan_ is read-only (only get_midi_clip_notes reaches the bridge); create_ also issues
create_midi_clip (which refuses non-empty slots). A fake bridge stands in for Ableton.
"""

from __future__ import annotations

import copy

import pytest

from abletongpt import server


_LOOP = {
    "track_index": 0,
    "track": "Keys",
    "clip_index": 0,
    "clip": "Riff",
    "length_beats": 4.0,
    "tempo": 120.0,
    "time_signature": [4, 4],
    "notes": [
        {"pitch": 48, "start_time": 0.0, "duration": 0.5, "velocity": 90, "probability": 1.0},
        {"pitch": 60, "start_time": 0.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        {"pitch": 64, "start_time": 1.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        {"pitch": 67, "start_time": 2.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        {"pitch": 72, "start_time": 3.0, "duration": 0.5, "velocity": 80, "probability": 1.0},
    ],
    "note_count": 5,
    "truncated": False,
}

_STRUCTURE = ["Intro", "Verse", "Build", "Chorus", "Outro"]


class FakeBridge:
    def __init__(self, occupied=frozenset()):
        self._occupied = set(occupied)
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            return copy.deepcopy(_LOOP)
        if command == "create_midi_clip":
            slot = (params["track_index"], params["clip_index"])
            if slot in self._occupied:
                raise ValueError("target clip slot is not empty")
            return {
                "clip_index": params["clip_index"],
                "note_count": len(params["notes"]),
                "length_beats": params["length_beats"],
            }
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_is_read_only(fake_bridge):
    plan = server.plan_developed_arrangement(0, 0, _STRUCTURE, section_repeats=2)
    assert plan["read_only"] is True
    assert plan["length_beats"] == 4.0 * 2 * len(_STRUCTURE)
    assert [command for command, _ in fake_bridge.calls] == ["get_midi_clip_notes"]
    assert len(plan["sections"]) == len(_STRUCTURE)


def test_create_writes_arrangement_to_destination_slot(fake_bridge):
    result = server.create_developed_arrangement(0, 0, _STRUCTURE, destination_clip_index=1, section_repeats=2)
    commands = [command for command, _ in fake_bridge.calls]
    assert commands == ["get_midi_clip_notes", "create_midi_clip"]
    write = fake_bridge.calls[1][1]
    assert write["track_index"] == 0  # defaults to source track
    assert write["clip_index"] == 1
    assert write["length_beats"] == 40.0
    assert len(write["notes"]) == result["note_count"]
    assert result["destination_clip_index"] == 1


def test_create_respects_destination_track_override(fake_bridge):
    server.create_developed_arrangement(0, 0, ["Verse", "Chorus"], destination_clip_index=0, destination_track_index=5)
    assert fake_bridge.calls[1][1]["track_index"] == 5


def test_create_refuses_occupied_slot(monkeypatch):
    bridge = FakeBridge(occupied={(0, 1)})
    monkeypatch.setattr(server, "bridge", bridge)
    with pytest.raises(ValueError, match="not empty"):
        server.create_developed_arrangement(0, 0, ["Verse", "Chorus"], destination_clip_index=1)


def test_create_guards_stale_fingerprint(fake_bridge):
    plan = server.plan_developed_arrangement(0, 0, ["Verse", "Chorus"])
    server.create_developed_arrangement(
        0, 0, ["Verse", "Chorus"], destination_clip_index=1,
        expected_source_fingerprint=plan["source_fingerprint"],
    )
    fake_bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.create_developed_arrangement(
            0, 0, ["Verse", "Chorus"], destination_clip_index=1, expected_source_fingerprint="deadbeef"
        )
    assert all(command != "create_midi_clip" for command, _ in fake_bridge.calls)
