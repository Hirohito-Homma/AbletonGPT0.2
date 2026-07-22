"""Tests for the ``apply_expression`` MCP tool (the write-back / create side).

``apply_expression`` reads a MIDI clip, runs the expression engine, checks the source
fingerprint, then sends the performed notes to the bridge's ``apply_expression_to_clip``
command. A fake bridge stands in for Ableton -- no socket, no Live process. The Remote
Script handler itself needs Live and is not exercised here.
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
    """Returns a canned clip for reads and records the apply command."""

    def __init__(self, clip=_CLIP_RESPONSE):
        self._clip = clip
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_midi_clip_notes":
            return dict(self._clip)
        if command == "apply_expression_to_clip":
            return {
                "track": self._clip["track"],
                "clip_index": params["clip_index"],
                "clip": self._clip["clip"],
                "length_beats": params["length_beats"],
                "note_count": len(params["notes"]),
                "applied_with_probability": True,
            }
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_apply_reads_then_writes(fake_bridge):
    result = server.apply_expression(0, 0, accent=1.0)

    commands = [command for command, _ in fake_bridge.calls]
    assert commands == ["get_midi_clip_notes", "apply_expression_to_clip"]
    assert result["applied"]["note_count"] == 3


def test_apply_forwards_performed_notes_with_probability(fake_bridge):
    server.apply_expression(0, 0, accent=1.0, weak_beat_probability=0.5)

    _, params = fake_bridge.calls[1]
    assert params["track_index"] == 0
    assert params["clip_index"] == 0
    assert params["length_beats"] == 8.0
    sent = {note["start_time"]: note for note in params["notes"]}
    assert sent[0.0]["velocity"] > 80  # downbeat accented
    assert sent[0.5]["probability"] == pytest.approx(0.5)  # off-beat probability lowered
    assert len(params["notes"]) == 3  # note count unchanged


def test_apply_preserves_note_count(fake_bridge):
    server.apply_expression(0, 0, swing=1.0, humanize=1.0, seed=3)

    _, params = fake_bridge.calls[1]
    assert len(params["notes"]) == len(_CLIP_RESPONSE["notes"])


def test_apply_honours_matching_fingerprint(fake_bridge):
    plan = server.plan_expression(0, 0, accent=0.5)
    fingerprint = plan["source"]["fingerprint"]

    server.apply_expression(0, 0, accent=0.5, expected_source_fingerprint=fingerprint)

    assert fake_bridge.calls[-1][0] == "apply_expression_to_clip"


def test_apply_refuses_stale_fingerprint_without_mutating(fake_bridge):
    with pytest.raises(ValueError):
        server.apply_expression(0, 0, expected_source_fingerprint="deadbeefdeadbeef")

    # The clip was read to compute the fingerprint, but nothing was written.
    commands = [command for command, _ in fake_bridge.calls]
    assert "apply_expression_to_clip" not in commands


def test_apply_rejects_negative_indices(fake_bridge):
    with pytest.raises(ValueError):
        server.apply_expression(-1, 0)
    assert fake_bridge.calls == []
