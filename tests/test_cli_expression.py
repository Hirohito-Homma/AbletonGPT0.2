"""Tests for the ``expression`` clip-editing CLI and its pure engine.

The CLI wraps the deterministic ``build_expression_plan`` engine, reading a MIDI-clip
JSON file. It is read-only: no Ableton, no network, no mutation of the source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from abletongpt.cli.expression import main
from abletongpt.expression import build_automation_envelope, build_expression_plan


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


# --- automation engine ----------------------------------------------------

def test_no_automation_by_default():
    plan = build_expression_plan(_CLIP)

    assert plan["automation"] == []
    assert plan["diff"]["automation_envelopes"] == 0
    assert plan["apply_contract"]["writes_automation_envelopes"] is False


def test_ramp_up_rises_across_the_clip():
    env = build_automation_envelope(8.0, shape="ramp_up", controller=11, depth=100, base=10)

    assert env["type"] == "midi_cc"
    assert env["controller"] == 11
    assert env["controller_name"] == "Expression"
    values = [point["value"] for point in env["points"]]
    assert values[0] == 10
    assert values[-1] == 110
    assert values == sorted(values)  # monotonically non-decreasing


def test_ramp_down_falls_across_the_clip():
    env = build_automation_envelope(8.0, shape="ramp_down", depth=100, base=0)

    values = [point["value"] for point in env["points"]]
    assert values[0] == 100
    assert values[-1] == 0
    assert values == sorted(values, reverse=True)


def test_arch_peaks_in_the_middle():
    env = build_automation_envelope(8.0, shape="arch", depth=100, base=0, resolution_beats=0.5)

    values = [point["value"] for point in env["points"]]
    assert values[0] == 0
    assert values[-1] == pytest.approx(0, abs=1)
    assert max(values) == max(values[len(values) // 4 : 3 * len(values) // 4])


def test_sine_oscillates_and_stays_in_range():
    env = build_automation_envelope(
        8.0, shape="sine", depth=100, base=10, cycles=2, resolution_beats=0.25
    )

    values = [point["value"] for point in env["points"]]
    assert all(0 <= value <= 127 for value in values)
    assert max(values) > min(values)  # actually moves


def test_automation_is_deterministic():
    first = build_automation_envelope(8.0, shape="sine", cycles=3)
    second = build_automation_envelope(8.0, shape="sine", cycles=3)

    assert first == second


def test_automation_rejects_bad_shape_and_range():
    with pytest.raises(ValueError):
        build_automation_envelope(8.0, shape="zigzag")
    with pytest.raises(ValueError):
        build_automation_envelope(8.0, shape="ramp_up", controller=200)
    with pytest.raises(ValueError):
        build_automation_envelope(8.0, shape="ramp_up", depth=200)


def test_plan_includes_requested_automation():
    plan = build_expression_plan(_CLIP, automation_shape="sine", automation_cc=74)

    assert plan["diff"]["automation_envelopes"] == 1
    assert plan["apply_contract"]["writes_automation_envelopes"] is True
    envelope = plan["automation"][0]
    assert envelope["controller"] == 74
    assert envelope["controller_name"] == "Filter Cutoff"


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


def test_cli_emits_automation_envelope(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(
        ["--clip", str(clip), "--automation", "arch", "--automation-cc", "11", "--json"]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["automation"]) == 1
    assert payload["automation"][0]["controller"] == 11
    assert payload["automation"][0]["shape"] == "arch"


def test_cli_human_output_reports_automation(tmp_path: Path, capsys):
    clip = _write_clip(tmp_path / "clip.json")

    rc = main(["--clip", str(clip), "--automation", "ramp_up"])

    assert rc == 0
    assert "automation: CC1 Mod Wheel  ramp_up" in capsys.readouterr().out


def test_cli_rejects_unknown_automation_shape_via_argparse(tmp_path: Path):
    clip = _write_clip(tmp_path / "clip.json")
    with pytest.raises(SystemExit):
        main(["--clip", str(clip), "--automation", "zigzag"])


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
