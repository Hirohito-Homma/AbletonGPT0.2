"""Tests for the audio-to-MIDI transcription logic (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.transcription import build_midi_from_chords, build_midi_from_melody


def _melody(notes):
    return {"notes": [{"midi": m, "start_seconds": s, "end_seconds": e} for m, s, e in notes]}


def _chords(segments):
    return {"chords": [{"chord": c, "start_seconds": s, "end_seconds": e} for c, s, e in segments]}


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


# --- chords ---


def test_major_chord_becomes_a_triad():
    # C at 0-2 s @ 120 BPM (= 0-4 beats). Root octave 3 -> C3 = 48, E3 = 52, G3 = 55.
    plan = build_midi_from_chords(_chords([("C", 0.0, 2.0)]), 120.0)

    assert plan["source"] == "chords"
    assert plan["chord_count"] == 1
    pitches = sorted(note["pitch"] for note in plan["notes"])
    assert pitches == [48, 52, 55]
    assert all(note["start_time"] == 0.0 and note["duration"] == 4.0 for note in plan["notes"])
    assert plan["length_beats"] == 4.0


def test_minor_chord_uses_a_flat_third():
    # Am -> A2 root at octave 3 (A = pc 9 -> 12*4+9 = 57), minor third +3, fifth +7.
    plan = build_midi_from_chords(_chords([("Am", 0.0, 1.0)]), 120.0)

    assert sorted(note["pitch"] for note in plan["notes"]) == [57, 60, 64]


def test_sharp_root_parsed():
    plan = build_midi_from_chords(_chords([("F#", 0.0, 1.0)]), 120.0)
    # F# = pc 6 -> 54 at octave 3; major triad 54/58/61.
    assert sorted(note["pitch"] for note in plan["notes"]) == [54, 58, 61]


def test_no_chord_segments_are_skipped():
    plan = build_midi_from_chords(_chords([("C", 0.0, 1.0), ("N", 1.0, 2.0), ("G", 2.0, 3.0)]), 120.0)

    assert plan["chord_count"] == 2
    assert plan["note_count"] == 6  # two triads


def test_octave_shifts_all_pitches():
    low = build_midi_from_chords(_chords([("C", 0.0, 1.0)]), 120.0, octave=2)
    high = build_midi_from_chords(_chords([("C", 0.0, 1.0)]), 120.0, octave=5)

    assert min(n["pitch"] for n in low["notes"]) == 36  # C2
    assert min(n["pitch"] for n in high["notes"]) == 72  # C5


def test_chords_reject_bad_octave_and_label():
    with pytest.raises(ValueError):
        build_midi_from_chords(_chords([("C", 0.0, 1.0)]), 120.0, octave=99)
    with pytest.raises(ValueError):
        build_midi_from_chords(_chords([("H", 0.0, 1.0)]), 120.0)
