"""Tests for the analyze_chord_progression MCP tool (read-only; no Live)."""

from __future__ import annotations

import copy

from abletongpt import server


def _clip(chords, chord_beats=4.0, signature=(4, 4)):
    notes = []
    for i, pitches in enumerate(chords):
        for pitch in pitches:
            notes.append(
                {
                    "pitch": pitch,
                    "start_time": i * chord_beats,
                    "duration": chord_beats,
                    "velocity": 100,
                    "probability": 1.0,
                }
            )
    return {
        "track_index": 0,
        "track": "Keys",
        "clip_index": 0,
        "clip": "Chords",
        "length_beats": len(chords) * chord_beats,
        "tempo": 120.0,
        "time_signature": list(signature),
        "notes": notes,
        "note_count": len(notes),
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
        raise AssertionError("unexpected bridge command: %s" % command)


# C - G - Am - F
_POP = [(60, 64, 67), (67, 71, 74), (69, 72, 76), (65, 69, 72)]


def test_explicit_key_analysis_is_read_only(monkeypatch):
    bridge = FakeBridge(_clip(_POP))
    monkeypatch.setattr(server, "bridge", bridge)

    report = server.analyze_chord_progression(0, 0, key="C major")

    assert report["read_only"] is True
    assert report["key"] == "C major"
    assert report["progression"] == "I - V - vi - IV"
    assert report["key_detected"] is False
    assert [command for command, _ in bridge.calls] == ["get_midi_clip_notes"]


def test_key_is_detected_when_omitted(monkeypatch):
    monkeypatch.setattr(server, "bridge", FakeBridge(_clip(_POP)))
    report = server.analyze_chord_progression(0, 0)

    assert report["key_detected"] is True
    assert report["tonic"] == "C"
    assert report["romans"] == ["I", "V", "vi", "IV"]


def test_default_segment_comes_from_time_signature(monkeypatch):
    # 3/4 -> one bar is 3 quarter-note beats.
    monkeypatch.setattr(server, "bridge", FakeBridge(_clip([(60, 64, 67)], chord_beats=3.0, signature=(3, 4))))
    report = server.analyze_chord_progression(0, 0, key="C")
    assert report["segment_beats"] == 3.0


def test_explicit_segment_beats_override(monkeypatch):
    monkeypatch.setattr(server, "bridge", FakeBridge(_clip(_POP)))
    report = server.analyze_chord_progression(0, 0, key="C", segment_beats=8.0)
    assert report["segment_beats"] == 8.0
