"""Tests for the plan_/apply_scale_quantize_midi MCP tools.

plan_ is read-only (only get_midi_clip_notes reaches the bridge); apply_ also issues
apply_expression_to_clip. A fake bridge stands in for Ableton -- no socket, no Live.
"""

from __future__ import annotations

import pytest

from abletongpt import server


# A clean C-major clip so the key detector resolves the tonic to C major.
_CMAJ = [60, 62, 64, 65, 67, 69, 71, 72]


def _clip(pitches):
    return {
        "track_index": 0,
        "track": "Keys",
        "clip_index": 0,
        "clip": "Lead",
        "length_beats": 8.0,
        "tempo": 120.0,
        "time_signature": [4, 4],
        "notes": [
            {"pitch": p, "start_time": float(i) * 0.5, "duration": 0.5, "velocity": 90, "probability": 1.0}
            for i, p in enumerate(pitches)
        ],
        "note_count": len(pitches),
        "truncated": False,
    }


class FakeBridge:
    def __init__(self, clip):
        self._clip = clip
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            import copy

            return copy.deepcopy(self._clip)
        if command == "apply_expression_to_clip":
            return {"applied_note_count": len(params.get("notes", []))}
        raise AssertionError("unexpected bridge command: %s" % command)


def _use(monkeypatch, clip):
    bridge = FakeBridge(clip)
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_with_explicit_key_snaps_out_of_scale(monkeypatch):
    bridge = _use(monkeypatch, _clip([60, 61, 66]))  # C, C#, F#
    plan = server.plan_scale_quantize_midi(0, 0, key="C", scale="major")

    assert plan["read_only"] is True
    assert plan["scale"] == "major"
    assert [n["pitch"] for n in plan["notes"]] == [60, 60, 65]  # C#->C, F#->F
    assert plan["changed_notes"] == 2
    assert [command for command, _ in bridge.calls] == ["get_midi_clip_notes"]


def test_plan_auto_scale_follows_detected_key(monkeypatch):
    _use(monkeypatch, _clip(_CMAJ))
    plan = server.plan_scale_quantize_midi(0, 0)  # no key, no scale -> detect

    assert plan["resolution"]["key_detected"] is True
    assert plan["resolution"]["tonic"] == "C"
    assert plan["scale"] == "major"  # auto follows the detected major mode
    assert plan["changed_notes"] == 0  # already in C major


def test_explicit_scale_overrides_key_mode(monkeypatch):
    _use(monkeypatch, _clip([60, 62, 63]))
    plan = server.plan_scale_quantize_midi(0, 0, key="C major", scale="dorian")

    assert plan["scale"] == "dorian"  # explicit scale wins over the key's major mode
    # C dorian allows Eb(63); D#/Eb stays, nothing forced to E.
    assert 63 in [n["pitch"] for n in plan["notes"]]


def test_apply_writes_back_and_guards_fingerprint(monkeypatch):
    bridge = _use(monkeypatch, _clip([60, 61]))

    plan = server.plan_scale_quantize_midi(0, 0, key="C", scale="major")
    fingerprint = plan["source_fingerprint"]

    applied = server.apply_scale_quantize_midi(0, 0, key="C", scale="major", expected_source_fingerprint=fingerprint)
    commands = [command for command, _ in bridge.calls]
    assert commands == ["get_midi_clip_notes", "get_midi_clip_notes", "apply_expression_to_clip"]
    write = bridge.calls[-1][1]
    assert [n["pitch"] for n in write["notes"]] == [60, 60]  # C#->C
    assert applied["changed_notes"] == 1

    bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.apply_scale_quantize_midi(0, 0, key="C", scale="major", expected_source_fingerprint="deadbeef")
    assert all(command != "apply_expression_to_clip" for command, _ in bridge.calls)
