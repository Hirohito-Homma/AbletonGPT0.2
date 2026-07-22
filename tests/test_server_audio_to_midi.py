"""Tests for the audio-to-MIDI server tools (plan/create).

The plan tool is read-only; the create tool issues exactly one ``create_midi_clip`` mutation.
The NumPy melody extraction is monkeypatched with a canned result, and a fake bridge stands
in for Ableton -- no socket, no Live process, no audio file.
"""

from __future__ import annotations

import pytest

from abletongpt import server


_MELODY = {
    "notes": [
        {"midi": 60, "start_seconds": 0.0, "end_seconds": 0.5, "note": "C4", "confidence": 1.0},
        {"midi": 64, "start_seconds": 0.5, "end_seconds": 1.0, "note": "E4", "confidence": 1.0},
    ],
    "note_names": ["C4", "E4"],
}


class FakeBridge:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "create_midi_clip":
            return {"track_index": params["track_index"], "clip_index": params["clip_index"],
                    "name": params["name"], "length_beats": params["length_beats"],
                    "note_count": len(params["notes"])}
        raise AssertionError("unexpected bridge command: %s" % command)


_CHORDS = {
    "chords": [
        {"chord": "C", "start_seconds": 0.0, "end_seconds": 1.0},
        {"chord": "G", "start_seconds": 1.0, "end_seconds": 2.0},
    ],
    "progression": ["C", "G"],
}


_ONSETS = {
    "onset_times": [0.0, 0.5, 1.0],
    "onsets": [
        {"time_seconds": 0.0, "strength": 1.0},
        {"time_seconds": 0.5, "strength": 0.6},
        {"time_seconds": 1.0, "strength": 0.8},
    ],
}
_BEATS = {
    "beat_times": [0.0, 0.5],
    "beats": [{"time_seconds": 0.0, "strength": 0.9}, {"time_seconds": 0.5, "strength": 0.7}],
}


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    monkeypatch.setattr(server, "extract_melody", lambda *args, **kwargs: dict(_MELODY))
    monkeypatch.setattr(server, "estimate_chords", lambda *args, **kwargs: dict(_CHORDS))
    monkeypatch.setattr(server, "detect_onsets", lambda *args, **kwargs: dict(_ONSETS))
    monkeypatch.setattr(server, "track_beats", lambda *args, **kwargs: dict(_BEATS))
    return bridge


def test_plan_is_read_only(fake_bridge):
    plan = server.plan_midi_from_audio_melody("loop.wav", tempo=120.0)

    assert plan["note_count"] == 2
    assert plan["notes"][0]["pitch"] == 60
    assert fake_bridge.calls == []  # planning never touches the bridge


def test_create_issues_one_create_midi_clip(fake_bridge):
    result = server.create_midi_from_audio_melody("loop.wav", track_index=1, clip_index=0, tempo=120.0)

    assert [command for command, _ in fake_bridge.calls] == ["create_midi_clip"]
    _command, params = fake_bridge.calls[0]
    assert params["track_index"] == 1
    assert params["clip_index"] == 0
    assert params["length_beats"] == 2.0  # notes span 0-2 beats at 120 BPM
    assert len(params["notes"]) == 2
    assert result["source"] == "audio_melody"
    assert result["note_count"] == 2


def test_create_rejects_bad_target_before_bridge(fake_bridge):
    with pytest.raises(ValueError):
        server.create_midi_from_audio_melody("loop.wav", track_index=-1, clip_index=0, tempo=120.0)
    assert fake_bridge.calls == []


def test_plan_chords_is_read_only(fake_bridge):
    plan = server.plan_midi_from_audio_chords("loop.wav", tempo=120.0)

    assert plan["source"] == "chords"
    assert plan["chord_count"] == 2
    assert plan["note_count"] == 6  # two triads
    assert fake_bridge.calls == []


def test_create_chords_issues_one_create_midi_clip(fake_bridge):
    result = server.create_midi_from_audio_chords("loop.wav", track_index=2, clip_index=1, tempo=120.0)

    assert [command for command, _ in fake_bridge.calls] == ["create_midi_clip"]
    _command, params = fake_bridge.calls[0]
    assert params["track_index"] == 2
    assert len(params["notes"]) == 6
    assert result["source"] == "audio_chords"
    assert result["chord_count"] == 2


def test_plan_rhythm_onsets_is_read_only(fake_bridge):
    plan = server.plan_midi_from_audio_rhythm("loop.wav", tempo=120.0, source="onsets", pitch=38)

    assert plan["note_count"] == 3
    assert all(note["pitch"] == 38 for note in plan["notes"])
    assert fake_bridge.calls == []


def test_create_rhythm_beats_issues_one_mutation(fake_bridge):
    result = server.create_midi_from_audio_rhythm(
        "loop.wav", track_index=0, clip_index=0, tempo=120.0, source="beats"
    )

    assert [command for command, _ in fake_bridge.calls] == ["create_midi_clip"]
    assert len(fake_bridge.calls[0][1]["notes"]) == 2
    assert result["source"] == "audio_rhythm"
    assert result["rhythm_source"] == "beats"


def test_rhythm_rejects_unknown_source(fake_bridge):
    with pytest.raises(ValueError):
        server.plan_midi_from_audio_rhythm("loop.wav", tempo=120.0, source="claps")
    assert fake_bridge.calls == []
