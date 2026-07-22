"""Tests for the legato / split note-length MCP tools (no Live)."""

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
        {"pitch": 60, "start_time": 0.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
        {"pitch": 60, "start_time": 1.0, "duration": 0.5, "velocity": 100, "probability": 1.0},
    ],
    "note_count": 2,
    "truncated": False,
}


class FakeBridge:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            return copy.deepcopy(_CLIP)
        if command == "apply_expression_to_clip":
            return {"applied_note_count": len(params.get("notes", []))}
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_legato_is_read_only(fake_bridge):
    plan = server.plan_legato_clip(0, 0)
    assert plan["read_only"] is True
    durations = {n["start_time"]: n["duration"] for n in plan["notes"]}
    assert durations[0.0] == 1.0  # extended to the next C at 1.0
    assert durations[1.0] == 3.0  # to the clip end
    assert [command for command, _ in fake_bridge.calls] == ["get_midi_clip_notes"]


def test_apply_legato_writes_back(fake_bridge):
    result = server.apply_legato_clip(0, 0)
    assert fake_bridge.calls[-1][0] == "apply_expression_to_clip"
    write = fake_bridge.calls[-1][1]
    assert write["expected_source_note_count"] == 2
    assert write["allow_note_count_change"] is False
    assert result["note_count"] == 2


def test_apply_split_multiplies_notes(fake_bridge):
    result = server.apply_split_notes(0, 0, divisions=2)
    write = fake_bridge.calls[-1][1]
    assert len(write["notes"]) == 4  # 2 notes x 2
    assert write["expected_source_note_count"] == 2
    assert write["allow_note_count_change"] is True
    assert result["note_count"] == 4
    assert result["source_note_count"] == 2


def test_split_guards_stale_fingerprint(fake_bridge):
    plan = server.plan_split_notes(0, 0, divisions=2)
    server.apply_split_notes(0, 0, divisions=2, expected_source_fingerprint=plan["source_fingerprint"])

    fake_bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.apply_split_notes(0, 0, divisions=2, expected_source_fingerprint="deadbeef")
    assert all(command != "apply_expression_to_clip" for command, _ in fake_bridge.calls)


def test_legato_guards_stale_fingerprint(fake_bridge):
    with pytest.raises(ValueError, match="changed after the plan"):
        server.apply_legato_clip(0, 0, expected_source_fingerprint="deadbeef")
    assert all(command != "apply_expression_to_clip" for command, _ in fake_bridge.calls)
