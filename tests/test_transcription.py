"""Tests for the audio-to-MIDI transcription logic (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.transcription import build_midi_from_melody


def _melody(notes):
    return {"notes": [{"midi": m, "start_seconds": s, "end_seconds": e} for m, s, e in notes]}


def test_converts_seconds_to_beats_at_tempo():
    # At 120 BPM, 1 s = 2 beats. A C4 from 0.0-0.5 s -> start 0, duration 1 beat.
    melody = _melody([(60, 0.0, 0.5), (62, 0.5, 1.0)])

    plan = build_midi_from_melody(melody, 120.0)

    assert plan["source"] == "melody"
    assert plan["tempo"] == 120.0
    assert plan["notes"][0] == {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}
    assert plan["notes"][1] == {"pitch": 62, "start_time": 1.0, "duration": 1.0, "velocity": 100}
    assert plan["note_count"] == 2


def test_clip_length_rounds_up_to_whole_beat():
    melody = _melody([(60, 0.0, 1.1)])  # 1.1 s @ 120 BPM = 2.2 beats

    plan = build_midi_from_melody(melody, 120.0)

    assert plan["length_beats"] == 3.0  # ceil(2.2)
    # Every note starts strictly inside the clip.
    assert all(note["start_time"] < plan["length_beats"] for note in plan["notes"])


def test_quantize_snaps_to_grid():
    # 0.3 s @ 120 BPM = 0.6 beats -> snaps to 0.5 with 1/8 (0.5-beat) grid.
    melody = _melody([(64, 0.3, 0.9)])  # 0.6-1.8 beats

    plan = build_midi_from_melody(melody, 120.0, quantize=0.5)

    note = plan["notes"][0]
    assert note["start_time"] == 0.5
    assert note["duration"] == 1.5  # end 1.8 -> 2.0, minus 0.5


def test_quantize_keeps_a_collapsed_note_audible():
    # A very short note whose start and end quantise to the same grid point keeps one step.
    melody = _melody([(60, 0.0, 0.02)])

    plan = build_midi_from_melody(melody, 120.0, quantize=0.5)

    assert plan["notes"][0]["duration"] == 0.5


def test_custom_velocity():
    plan = build_midi_from_melody(_melody([(60, 0.0, 0.5)]), 120.0, velocity=80)
    assert plan["notes"][0]["velocity"] == 80


def test_empty_melody_yields_empty_plan():
    plan = build_midi_from_melody(_melody([]), 120.0)
    assert plan["notes"] == []
    assert plan["note_count"] == 0
    assert plan["length_beats"] == 1.0


@pytest.mark.parametrize("bad_tempo", [0.0, -10.0])
def test_rejects_non_positive_tempo(bad_tempo):
    with pytest.raises(ValueError):
        build_midi_from_melody(_melody([(60, 0.0, 0.5)]), bad_tempo)


def test_rejects_bad_quantize_and_velocity():
    with pytest.raises(ValueError):
        build_midi_from_melody(_melody([(60, 0.0, 0.5)]), 120.0, quantize=32.0)
    with pytest.raises(ValueError):
        build_midi_from_melody(_melody([(60, 0.0, 0.5)]), 120.0, velocity=200)
