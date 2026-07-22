"""Tests for the plan_/apply_remap_progression_to_key MCP tools.

plan_ is read-only (only get_midi_clip_notes reaches the bridge); apply_ also issues
apply_expression_to_clip. A fake bridge stands in for Ableton -- no socket, no Live.
"""

from __future__ import annotations

import copy

import pytest

from abletongpt import server


# A clean C-major clip so the key detector resolves the tonic to C major.
_CMAJ = [60, 62, 64, 65, 67, 69, 71, 72]


def _clip(pitches):
    return {
        "track_index": 0,
        "track": "Keys",
        "clip_index": 0,
        "clip": "Chords",
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
            return copy.deepcopy(self._clip)
        if command == "apply_expression_to_clip":
            return {"applied_note_count": len(params.get("notes", []))}
        raise AssertionError("unexpected bridge command: %s" % command)


def _use(monkeypatch, clip):
    bridge = FakeBridge(clip)
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_detects_source_and_converts_to_parallel_minor(monkeypatch):
    bridge = _use(monkeypatch, _clip(_CMAJ))
    plan = server.plan_remap_progression_to_key(0, 0, target_key="C minor")

    resolution = plan["resolution"]
    assert resolution["source_key_detected"] is True
    assert resolution["source_key"] == "C major"
    assert resolution["target_key"] == "C minor"
    # E, A, B lower to Eb, Ab, Bb; the rest stay.
    assert [n["pitch"] for n in plan["notes"]] == [60, 62, 63, 65, 67, 68, 70, 72]
    assert plan["changed_notes"] == 3
    assert [command for command, _ in bridge.calls] == ["get_midi_clip_notes"]


def test_explicit_source_key_skips_detection(monkeypatch):
    _use(monkeypatch, _clip([60, 64, 67]))
    plan = server.plan_remap_progression_to_key(
        0, 0, target_key="G", source_key="C major"
    )
    assert plan["resolution"]["source_key_detected"] is False
    # C major -> G major, degree-locked +7.
    assert [n["pitch"] for n in plan["notes"]] == [67, 71, 74]


def test_explicit_scales_override_key_modes(monkeypatch):
    _use(monkeypatch, _clip([60, 62, 63]))
    plan = server.plan_remap_progression_to_key(
        0, 0, target_key="C", target_scale="dorian", source_key="C", source_scale="minor"
    )
    assert plan["resolution"]["source_scale"] == "minor"
    assert plan["resolution"]["target_scale"] == "dorian"


def test_mismatched_degree_counts_surface_as_error(monkeypatch):
    _use(monkeypatch, _clip([60, 62, 64]))
    with pytest.raises(ValueError, match="same"):
        server.plan_remap_progression_to_key(
            0, 0, target_key="C", target_scale="major_pentatonic", source_key="C major"
        )


def test_apply_writes_back_and_guards_fingerprint(monkeypatch):
    bridge = _use(monkeypatch, _clip([60, 64, 67]))

    plan = server.plan_remap_progression_to_key(0, 0, target_key="C minor", source_key="C major")
    fingerprint = plan["source_fingerprint"]

    applied = server.apply_remap_progression_to_key(
        0, 0, target_key="C minor", source_key="C major", expected_source_fingerprint=fingerprint
    )
    assert bridge.calls[-1][0] == "apply_expression_to_clip"
    assert [n["pitch"] for n in bridge.calls[-1][1]["notes"]] == [60, 63, 67]  # E->Eb
    assert applied["changed_notes"] == 1

    bridge.calls.clear()
    with pytest.raises(ValueError, match="changed after the plan"):
        server.apply_remap_progression_to_key(
            0, 0, target_key="C minor", source_key="C major", expected_source_fingerprint="deadbeef"
        )
    assert all(command != "apply_expression_to_clip" for command, _ in bridge.calls)
