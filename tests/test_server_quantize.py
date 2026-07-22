"""Tests for the plan_/apply_quantize_midi_timing MCP tools.

plan_ is read-only (only get_midi_clip_notes reaches the bridge); apply_ also issues
apply_expression_to_clip. A fake bridge stands in for Ableton -- no socket, no Live.
"""

from __future__ import annotations

import copy

import pytest

from abletongpt import server


def _clip(starts):
    return {
        "track_index": 0,
        "track": "Drums",
        "clip_index": 0,
        "clip": "Beat",
        "length_beats": 4.0,
        "tempo": 120.0,
        "time_signature": [4, 4],
        "notes": [
            {"pitch": 36, "start_time": float(s), "duration": 0.25, "velocity": 100, "probability": 1.0}
            for s in starts
        ],
        "note_count": len(starts),
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


def test_plan_is_read_only_and_snaps(monkeypatch):
    bridge = _use(monkeypatch, _clip([0.06, 0.47, 0.98]))
    plan = server.plan_quantize_midi_timing(0, 0, grid_beats=0.5, strength=1.0)

    assert plan["read_only"] is True
    assert [n["start_time"] for n in plan["notes"]] == [0.0, 0.5, 1.0]
    assert plan["moved_notes"] == 3
    assert [command for command, _ in bridge.calls] == ["get_midi_clip_notes"]


def test_plan_swing_is_forwarded(monkeypatch):
    _use(monkeypatch, _clip([0.0, 0.5]))
    plan = server.plan_quantize_midi_timing(0, 0, grid_beats=0.5, strength=1.0, swing=0.5)
    assert plan["swing"] == 0.5
    assert [n["start_time"] for n in plan["notes"]][1] == pytest.approx(0.625)


def test_apply_writes_back_and_guards_fingerprint(monkeypatch):
    bridge = _use(monkeypatch, _clip([0.06, 0.47]))

    plan = server.plan_quantize_midi_timing(0, 0, grid_beats=0.5)
    fingerprint = plan["source_fingerprint"]

    applied = server.apply_quantize_midi_timing(0, 0, grid_beats=0.5, expected_source_fingerprint=fingerprint)
    assert bridge.calls[-1][0] == "apply_expression_to_clip"
    assert [n["start_time"] for n in bridge.calls[-1][1]["notes"]] == [0.0, 0.5]
    assert applied["moved_notes"] == 2

    bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.apply_quantize_midi_timing(0, 0, grid_beats=0.5, expected_source_fingerprint="deadbeef")
    assert all(command != "apply_expression_to_clip" for command, _ in bridge.calls)


def test_bad_grid_surfaces_as_error(monkeypatch):
    _use(monkeypatch, _clip([0.1]))
    with pytest.raises(ValueError):
        server.plan_quantize_midi_timing(0, 0, grid_beats=0.0)
