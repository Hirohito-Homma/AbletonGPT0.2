"""Tests for the ``contextual`` analyze/plan CLI.

The CLI wraps the pure ``analyze_midi_context`` / ``build_complementary_track_plan``
engines, reading a MIDI-clip JSON file. No Ableton, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abletongpt.cli.contextual import main


_CLIP = {
    "length_beats": 16.0,
    "tempo": 120,
    "track": "Chords",
    "notes": [
        {"pitch": 60, "start_time": 0.0, "duration": 2.0, "velocity": 90},
        {"pitch": 64, "start_time": 0.0, "duration": 2.0, "velocity": 90},
        {"pitch": 67, "start_time": 0.0, "duration": 2.0, "velocity": 90},
        {"pitch": 62, "start_time": 4.0, "duration": 2.0, "velocity": 90},
        {"pitch": 65, "start_time": 4.0, "duration": 2.0, "velocity": 90},
        {"pitch": 69, "start_time": 4.0, "duration": 2.0, "velocity": 90},
    ],
}


def _write_clip(path: Path, clip=_CLIP) -> Path:
    path.write_text(json.dumps(clip), encoding="utf-8")
    return path


def test_analyze_human_output_reports_context(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(["analyze", "--clip", str(clip)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "role: chords" in out
    assert "key: C major" in out
    assert "range:" in out


def test_analyze_json_is_read_only_and_machine_readable(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(["analyze", "--clip", str(clip), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True
    assert payload["musical_context"]["source_role"] == "chords"
    assert payload["musical_context"]["key"]["tonic"] == "C"


def test_plan_generates_complementary_track(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(
        ["plan", "--clip", str(clip), "--target-role", "bass", "--seed", "3", "--json"]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True
    assert payload["target_track"]["role"] == "bass"
    assert payload["target_track"]["notes"]  # produced some notes


def test_plan_is_deterministic_for_a_seed(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")
    args = ["plan", "--clip", str(clip), "--target-role", "bass", "--seed", "3", "--json"]

    main(args)
    first = json.loads(capsys.readouterr().out)
    main(args)
    second = json.loads(capsys.readouterr().out)

    assert first == second


def test_missing_clip_file_exits_2(tmp_path: Path, capsys):
    rc = main(["analyze", "--clip", str(tmp_path / "nope.json")])

    assert rc == 2
    assert "contextual:" in capsys.readouterr().err


def test_clip_without_notes_exits_2(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "empty.json", {"length_beats": 8.0, "notes": []})

    rc = main(["analyze", "--clip", str(clip)])

    assert rc == 2
    assert "no notes" in capsys.readouterr().err


def test_plan_rejects_unknown_target_role_via_argparse(tmp_path: Path):
    clip = _write_clip(tmp_path / "clip.json")
    with pytest.raises(SystemExit):
        main(["plan", "--clip", str(clip), "--target-role", "kazoo"])
