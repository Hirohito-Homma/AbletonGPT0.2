"""Tests for MIDI scale quantization (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.scale import (
    build_scale_quantize_plan,
    parse_scale,
    scale_pitch_classes,
    snap_pitch,
)


def _clip(pitches, length=4.0):
    return {
        "length_beats": length,
        "notes": [
            {"pitch": p, "start_time": float(i) * 0.25, "duration": 0.25, "velocity": 100, "probability": 1.0}
            for i, p in enumerate(pitches)
        ],
    }


def test_parse_scale_normalizes_and_aliases():
    assert parse_scale("Major") == "major"
    assert parse_scale("natural minor") == "minor"
    assert parse_scale("aeolian") == "minor"
    assert parse_scale("ionian") == "major"
    assert parse_scale("major-pentatonic") == "major_pentatonic"


def test_parse_scale_rejects_unknown():
    with pytest.raises(ValueError):
        parse_scale("bebop-super-locrian")


def test_scale_pitch_classes_c_major():
    assert scale_pitch_classes(0, "major") == {0, 2, 4, 5, 7, 9, 11}
    # A minor shares the white keys.
    assert scale_pitch_classes(9, "minor") == {0, 2, 4, 5, 7, 9, 11}


def test_snap_pitch_leaves_in_scale_notes():
    c_major = scale_pitch_classes(0, "major")
    assert snap_pitch(60, c_major) == 60  # C stays
    assert snap_pitch(64, c_major) == 64  # E stays


def test_snap_pitch_moves_out_of_scale_to_nearest():
    c_major = scale_pitch_classes(0, "major")
    assert snap_pitch(61, c_major) == 60  # C# -> C (down 1)
    assert snap_pitch(66, c_major) == 65  # F# -> F (down 1, tie with G broken downward)
    assert snap_pitch(63, c_major) == 62  # D# -> D (down 1)


def test_snap_pitch_tie_breaks_down():
    # C# (1) sits one semitone from both C (0) and D (2); tie -> down to C.
    assert snap_pitch(61, {0, 2}) == 60


def test_snap_pitch_stays_in_range_at_extremes():
    # 127 is G; in C major (no G? G is in major) -> use a scale without the top pc.
    only_c = {0}
    assert snap_pitch(127, only_c) == 120  # nearest C at/under 127, never > 127
    assert snap_pitch(1, only_c) == 0
    assert 0 <= snap_pitch(126, only_c) <= 127


def test_build_plan_snaps_and_counts_changes():
    plan = build_scale_quantize_plan(_clip([60, 61, 64, 66]), 0, "major")

    assert plan["scale"] == "major"
    assert [n["pitch"] for n in plan["notes"]] == [60, 60, 64, 65]  # 61->60, 66->65
    assert plan["changed_notes"] == 2
    assert plan["note_count"] == 4
    assert plan["tonic_pitch_class"] == 0


def test_build_plan_preserves_timing_and_probability():
    clip = _clip([61])
    clip["notes"][0]["probability"] = 0.4
    plan = build_scale_quantize_plan(clip, 0, "major")

    note = plan["notes"][0]
    assert note["pitch"] == 60
    assert note["start_time"] == 0.0
    assert note["duration"] == 0.25
    assert note["probability"] == 0.4


def test_chromatic_scale_changes_nothing():
    plan = build_scale_quantize_plan(_clip([60, 61, 62, 63]), 0, "chromatic")
    assert plan["changed_notes"] == 0
    assert [n["pitch"] for n in plan["notes"]] == [60, 61, 62, 63]


def test_fingerprint_is_source_based():
    clip = _clip([60, 61])
    a = build_scale_quantize_plan(clip, 0, "major")["source_fingerprint"]
    b = build_scale_quantize_plan(clip, 0, "minor")["source_fingerprint"]
    assert a == b  # same source -> same fingerprint regardless of scale


def test_empty_clip_rejected():
    with pytest.raises(ValueError):
        build_scale_quantize_plan({"length_beats": 4.0, "notes": []}, 0, "major")
