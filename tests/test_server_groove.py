"""Tests for the plan_/apply_velocity_groove MCP tools.

plan_ is read-only (only get_midi_clip_notes reaches the bridge); apply_ also issues
apply_expression_to_clip. A fake bridge stands in for Ableton -- no socket, no Live.
"""

from __future__ import annotations

import copy

import pytest

from abletongpt import server


def _clip(velocities):
    return {
        "track_index": 0,
        "track": "Keys",
        "clip_index": 0,
        "clip": "Part",
        "length_beats": 4.0,
        "tempo": 120.0,
        "time_signature": [4, 4],
        "notes": [
            {"pitch": 60, "start_time": float(i), "duration": 0.5, "velocity": int(v), "probability": 1.0}
            for i, v in enumerate(velocities)
        ],
        "note_count": len(velocities),
        "truncated": False,
    }


class FakeBridge:
    def __init__(self, clip):
        self._clip = clip
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            return copy.deepcopy(self._clip)
        if command == "apply_expression_to_clip":
            return {"applied_note_count": len(params.get("notes", []))}
        raise AssertionError("unexpected bridge command: %s" % command)


def _use(monkeypatch, clip):
    bridge = FakeBridge(clip)
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_is_read_only_and_compresses(monkeypatch):
    bridge = _use(monkeypatch, _clip([60, 80, 100]))
    plan = server.plan_velocity_groove(0, 0, dynamics=-1.0)

    assert plan["read_only"] is True
    assert [n["velocity"] for n in plan["notes"]] == [80, 80, 80]
    assert [command for command, _ in bridge.calls] == ["get_midi_clip_notes"]


def test_plan_accent_pattern_forwarded(monkeypatch):
    _use(monkeypatch, _clip([80, 80, 80, 80]))
    plan = server.plan_velocity_groove(0, 0, accent_pattern=[1.25, 0.75], grid_beats=1.0)
    assert [n["velocity"] for n in plan["notes"]] == [100, 60, 100, 60]
    assert plan["accent_pattern"] == [1.25, 0.75]


def test_apply_writes_back_and_guards_fingerprint(monkeypatch):
    bridge = _use(monkeypatch, _clip([60, 80, 100]))

    plan = server.plan_velocity_groove(0, 0, dynamics=1.0)
    fingerprint = plan["source_fingerprint"]

    applied = server.apply_velocity_groove(0, 0, dynamics=1.0, expected_source_fingerprint=fingerprint)
    assert bridge.calls[-1][0] == "apply_expression_to_clip"
    assert [n["velocity"] for n in bridge.calls[-1][1]["notes"]] == [40, 80, 120]
    assert applied["changed_notes"] == 2

    bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.apply_velocity_groove(0, 0, dynamics=1.0, expected_source_fingerprint="deadbeef")
    assert all(command != "apply_expression_to_clip" for command, _ in bridge.calls)


def test_bad_parameter_surfaces_as_error(monkeypatch):
    _use(monkeypatch, _clip([80]))
    with pytest.raises(ValueError):
        server.plan_velocity_groove(0, 0, crescendo=2.0)
