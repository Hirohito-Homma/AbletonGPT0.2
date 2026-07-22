"""Tests for the ``expression`` clip-editing CLI and its pure engine.

The CLI wraps the deterministic ``build_expression_plan`` engine, reading a MIDI-clip
JSON file. It is read-only: no Ableton, no network, no mutation of the source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abletongpt.cli.expression import main
from abletongpt.expression import build_expression_plan


_CLIP = {
    "length_beats": 8.0,
    "track": "Keys",
    "notes": [
        # On the beat (downbeat) and off the beat ("and"), alternating.
        {"pitch": 60, "start_time": 0.0, "duration": 0.5, "velocity": 80},
        {"pitch": 62, "start_time": 0.5, "duration": 0.5, "velocity": 80},
        {"pitch": 64, "start_time": 1.0, "duration": 0.5, "velocity": 80},
        {"pitch": 65, "start_time": 1.5, "duration": 0.5, "velocity": 80},
        {"pitch": 67, "start_time": 2.0, "duration": 0.5, "velocity": 80},
    ],
}


def _write_clip(path: Path, clip=_CLIP) -> Path:
    path.write_text(json.dumps(clip), encoding="utf-8")
    return path


# --- engine ---------------------------------------------------------------

def test_defaults_are_a_no_op_on_notes():
    plan = build_expression_plan(_CLIP)

    assert plan["read_only"] is True
    for original, edited in zip(
        sorted(_CLIP["notes"], key=lambda n: (n["start_time"], n["pitch"])),
        plan["notes"],
    ):
        assert edited["pitch"] == original["pitch"]
        assert edited["start_time"] == pytest.approx(original["start_time"])
        assert edited["velocity"] == original["velocity"]
        assert edited["probability"] == 1.0
    assert plan["diff"]["timing"]["max_shift_beats"] == 0.0


def test_accent_boosts_downbeats_and_softens_offbeats():
    plan = build_expression_plan(_CLIP, accent=1.0)

    by_start = {note["start_time"]: note for note in plan["notes"]}
    assert by_start[0.0]["velocity"] > 80  # downbeat boosted
    assert by_start[0.5]["velocity"] < 80  # off-beat softened


def test_swing_delays_offbeat_notes_only():
    plan = build_expression_plan(_CLIP, swing=1.0, grid_beats=0.5)

    by_pitch = {note["pitch"]: note for note in plan["notes"]}
    assert by_pitch[60]["start_time"] == pytest.approx(0.0)  # on-grid, unmoved
    assert by_pitch[62]["start_time"] > 0.5  # off-grid, delayed


def test_weak_beat_probability_only_lowers_offbeats():
    plan = build_expression_plan(_CLIP, weak_beat_probability=0.6)

    by_pitch = {note["pitch"]: note for note in plan["notes"]}
    assert by_pitch[60]["probability"] == 1.0  # on-grid untouched
    assert by_pitch[62]["probability"] == pytest.approx(0.6)  # off-grid lowered


def test_engine_is_deterministic_for_a_seed():
    first = build_expression_plan(_CLIP, humanize=0.8, seed=5)
    second = build_expression_plan(_CLIP, humanize=0.8, seed=5)

    assert first == second


def test_out_of_range_setting_is_rejected():
    with pytest.raises(ValueError):
        build_expression_plan(_CLIP, accent=1.5)


def test_notes_stay_inside_the_clip_after_shaping():
    clip = {
        "length_beats": 2.0,
        "notes": [{"pitch": 60, "start_time": 1.5, "duration": 0.5, "velocity": 90}],
    }
    plan = build_expression_plan(clip, swing=1.0, humanize=1.0, seed=1)

    note = plan["notes"][0]
    assert 0.0 <= note["start_time"] < 2.0
    assert note["start_time"] + note["duration"] <= 2.0 + 1e-6


# --- CLI ------------------------------------------------------------------

def test_cli_human_output_reports_transforms(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(["--clip", str(clip), "--accent", "0.5"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "source: Keys" in out
    assert "velocity:" in out


def test_cli_json_is_read_only_and_machine_readable(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(["--clip", str(clip), "--swing", "0.4", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True
    assert payload["apply_contract"]["adds_or_deletes_notes"] is False
    assert len(payload["notes"]) == len(_CLIP["notes"])


def test_cli_missing_clip_file_exits_2(tmp_path: Path, capsys):
    rc = main(["--clip", str(tmp_path / "nope.json")])

    assert rc == 2
    assert "expression:" in capsys.readouterr().err


def test_cli_clip_without_notes_exits_2(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "empty.json", {"length_beats": 8.0, "notes": []})

    rc = main(["--clip", str(clip)])

    assert rc == 2
    assert "no notes" in capsys.readouterr().err


def test_cli_rejects_out_of_range_setting_cleanly(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(["--clip", str(clip), "--humanize", "2.0"])

    assert rc == 2
    assert "expression:" in capsys.readouterr().err
