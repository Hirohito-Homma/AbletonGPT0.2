"""Tests for the plan_/apply_transpose_midi MCP tools.

plan_transpose_midi is read-only (only get_midi_clip_notes reaches the bridge); apply_ also
issues apply_expression_to_clip. A fake bridge stands in for Ableton -- no socket, no Live.
"""

from __future__ import annotations

import pytest

from abletongpt import server


# A clear C-major clip so the key detector resolves the tonic to C.
_CLIP = {
    "track_index": 0,
    "track": "Keys",
    "clip_index": 0,
    "clip": "Melody",
    "length_beats": 8.0,
    "tempo": 120.0,
    "time_signature": [4, 4],
    "notes": [
        {"pitch": p, "start_time": float(i) * 0.5, "duration": 0.5, "velocity": 90, "probability": 1.0}
        for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72])
    ],
    "note_count": 8,
    "truncated": False,
}


class FakeBridge:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            return {key: (list(value) if isinstance(value, list) else value) for key, value in _CLIP.items()}
        if command == "apply_expression_to_clip":
            return {"applied_note_count": len(params.get("notes", [])), "length_beats": params.get("length_beats")}
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_by_semitones_is_read_only(fake_bridge):
    plan = server.plan_transpose_midi(0, 0, semitones=3)

    assert plan["read_only"] is True
    assert plan["semitones"] == 3
    assert plan["resolution"]["mode"] == "semitones"
    assert [n["pitch"] for n in plan["notes"]][:1] == [63]  # 60 + 3
    assert [command for command, _ in fake_bridge.calls] == ["get_midi_clip_notes"]


def test_plan_to_target_key_detects_source_and_computes_shift(fake_bridge):
    plan = server.plan_transpose_midi(0, 0, target_key="G major")

    resolution = plan["resolution"]
    assert resolution["mode"] == "to_key"
    assert resolution["source_key"] == "C major"
    assert resolution["target_key"] == "G major"
    assert resolution["source_key_detected"] is True
    # C -> G nearest is down a fourth.
    assert plan["semitones"] == -5


def test_plan_to_target_key_accepts_camelot_and_source_override(fake_bridge):
    # 9B == G major; explicit source_key skips detection.
    plan = server.plan_transpose_midi(0, 0, target_key="9B", source_key="C major", direction="up")

    assert plan["resolution"]["source_key_detected"] is False
    assert plan["resolution"]["target_key"] == "G major"
    assert plan["semitones"] == 7  # up a fifth


def test_apply_writes_transposed_notes_back(fake_bridge):
    applied = server.apply_transpose_midi(0, 0, semitones=2)

    commands = [command for command, _ in fake_bridge.calls]
    assert commands == ["get_midi_clip_notes", "apply_expression_to_clip"]
    write = fake_bridge.calls[1][1]
    assert write["track_index"] == 0 and write["clip_index"] == 0
    assert [n["pitch"] for n in write["notes"]][:1] == [62]  # 60 + 2


def test_apply_rejects_stale_fingerprint(fake_bridge):
    plan = server.plan_transpose_midi(0, 0, semitones=2)
    fingerprint = plan["source_fingerprint"]

    # Correct fingerprint applies.
    server.apply_transpose_midi(0, 0, semitones=2, expected_source_fingerprint=fingerprint)

    # A wrong fingerprint is refused before any write.
    fake_bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.apply_transpose_midi(0, 0, semitones=2, expected_source_fingerprint="deadbeef")
    assert all(command != "apply_expression_to_clip" for command, _ in fake_bridge.calls)
