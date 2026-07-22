from __future__ import annotations

import json
from pathlib import Path

import pytest

from abletongpt.cli.arrange import main
from abletongpt.cli.jobs import main as jobs_main
from abletongpt.cli.serialization import arrangement_from_dict
from abletongpt.jobs import load_job_plan, load_step_statuses


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- template --------------------------------------------------------------------

def test_template_writes_editable_arrangement_json(tmp_path: Path, capsys):
    out = tmp_path / "arr.json"

    rc = main(["template", "--name", "demo_song", "--out", str(out)])

    assert rc == 0
    assert out.exists()
    document = _read(out)
    assert document["name"] == "demo_song"
    assert len(document["sections"]) >= 3
    # It round-trips back into the model without error.
    plan = arrangement_from_dict(document)
    assert plan.name == "demo_song"
    assert "section" in capsys.readouterr().out


# --- create-simple ---------------------------------------------------------------

def test_create_simple_output_is_consumable_by_jobs_create(tmp_path: Path):
    arr = tmp_path / "arr.json"
    rc = main(["create-simple", "--name", "dark_tech_house_demo", "--out", str(arr)])
    assert rc == 0

    document = _read(arr)
    assert document["name"] == "dark_tech_house_demo"
    section_ids = [s["section_id"] for s in document["sections"]]
    assert section_ids == ["intro", "groove", "break", "drop", "outro"]
    # Bars match the specified contiguous 1-based layout.
    assert document["sections"][0]["start_bar"] == 1
    assert document["sections"][0]["length_bars"] == 8

    # Hand it straight to `jobs create` -> a real job plan, no editing needed.
    plan_out = tmp_path / "plan.json"
    rc2 = jobs_main(["create", "--arrangement", str(arr), "--out", str(plan_out)])
    assert rc2 == 0
    job_plan = load_job_plan(plan_out)
    assert len(job_plan.steps) == 5
    assert all(step.command == "place_scene" for step in job_plan.steps)
    assert set(load_step_statuses(plan_out).values())  # readable statuses


# --- template / create-simple --json ---------------------------------------------

def test_template_json_reports_written_file(tmp_path: Path, capsys):
    out = tmp_path / "arr.json"

    rc = main(["template", "--name", "demo", "--out", str(out), "--json"])

    assert rc == 0
    assert out.exists()  # the file is still written
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "demo"
    assert payload["path"] == str(out)
    assert payload["section_count"] == len(_read(out)["sections"])
    assert isinstance(payload["total_bars"], int)


def test_create_simple_json_reports_written_file(tmp_path: Path, capsys):
    out = tmp_path / "arr.json"

    rc = main(["create-simple", "--name", "song", "--out", str(out), "--json"])

    assert rc == 0
    assert out.exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "song"
    assert payload["path"] == str(out)
    assert payload["section_count"] == 5


# --- validate --------------------------------------------------------------------

def test_validate_accepts_a_valid_arrangement(tmp_path: Path, capsys):
    arr = tmp_path / "arr.json"
    main(["create-simple", "--name", "ok", "--out", str(arr)])

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "5 section" in out
    assert "bar" in out


def _write(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_validate_rejects_duplicate_section_ids(tmp_path: Path, capsys):
    arr = _write(
        tmp_path / "dup.json",
        {
            "name": "dup",
            "sections": [
                {"section_id": "x", "name": "A", "source_scene": "a", "start_bar": 1, "length_bars": 8},
                {"section_id": "x", "name": "B", "source_scene": "b", "start_bar": 9, "length_bars": 8},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 1
    assert "duplicate section_id" in capsys.readouterr().err


def test_validate_rejects_non_positive_start_bar(tmp_path: Path, capsys):
    arr = _write(
        tmp_path / "bad_start.json",
        {
            "name": "bad",
            "sections": [
                {"section_id": "x", "name": "A", "source_scene": "a", "start_bar": 0, "length_bars": 8},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 1
    assert "start_bar must be positive" in capsys.readouterr().err


def test_validate_rejects_non_positive_length_bars(tmp_path: Path, capsys):
    arr = _write(
        tmp_path / "bad_len.json",
        {
            "name": "bad",
            "sections": [
                {"section_id": "x", "name": "A", "source_scene": "a", "start_bar": 1, "length_bars": 0},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 1
    assert "length_bars must be positive" in capsys.readouterr().err


def test_validate_rejects_overlapping_sections(tmp_path: Path, capsys):
    # 'a' covers bars 1-8; 'b' starts at bar 5, inside 'a' -> overlap.
    arr = _write(
        tmp_path / "overlap.json",
        {
            "name": "overlap",
            "sections": [
                {"section_id": "a", "name": "A", "source_scene": "a", "start_bar": 1, "length_bars": 8},
                {"section_id": "b", "name": "B", "source_scene": "b", "start_bar": 5, "length_bars": 8},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "overlaps" in err
    assert "'b'" in err and "'a'" in err


def test_validate_allows_gaps_between_sections(tmp_path: Path, capsys):
    # 'a' ends at bar 8, 'b' starts at bar 20: a gap, which is legitimate (silence),
    # so validation must accept it rather than flag it like an overlap.
    arr = _write(
        tmp_path / "gap.json",
        {
            "name": "gap",
            "sections": [
                {"section_id": "a", "name": "A", "source_scene": "a", "start_bar": 1, "length_bars": 8},
                {"section_id": "b", "name": "B", "source_scene": "b", "start_bar": 20, "length_bars": 8},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 0
    assert "2 section" in capsys.readouterr().out


def test_validate_accepts_contiguous_touching_sections(tmp_path: Path, capsys):
    # 'a' covers bars 1-8, 'b' starts at bar 9 (exactly where 'a' ends): touching,
    # not overlapping. The exclusive end bar must not be treated as a shared bar.
    arr = _write(
        tmp_path / "touch.json",
        {
            "name": "touch",
            "sections": [
                {"section_id": "a", "name": "A", "source_scene": "a", "start_bar": 1, "length_bars": 8},
                {"section_id": "b", "name": "B", "source_scene": "b", "start_bar": 9, "length_bars": 8},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 0
    assert "2 section" in capsys.readouterr().out


# --- validate --strict -----------------------------------------------------------

def _gapped(path: Path) -> Path:
    # 'a' ends at bar 8, 'b' starts at bar 20: an 11-bar gap (bars 9-19 unused).
    return _write(
        path,
        {
            "name": "gap",
            "sections": [
                {"section_id": "a", "name": "A", "source_scene": "a", "start_bar": 1, "length_bars": 8},
                {"section_id": "b", "name": "B", "source_scene": "b", "start_bar": 20, "length_bars": 8},
            ],
        },
    )


def test_validate_strict_flags_gap_that_default_allows(tmp_path: Path, capsys):
    arr = _gapped(tmp_path / "gap.json")

    rc = main(["validate", "--arrangement", str(arr), "--strict"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "gap between section 'a' and 'b'" in err
    assert "bars 9-19 unused" in err


def test_validate_without_strict_still_allows_gap(tmp_path: Path, capsys):
    # The same gapped arrangement must remain valid without --strict (default behavior).
    arr = _gapped(tmp_path / "gap.json")

    rc = main(["validate", "--arrangement", str(arr)])

    assert rc == 0
    assert "gap" not in capsys.readouterr().err


def test_validate_strict_flags_arrangement_not_starting_at_bar_1(tmp_path: Path, capsys):
    arr = _write(
        tmp_path / "lead.json",
        {
            "name": "lead",
            "sections": [
                {"section_id": "a", "name": "A", "source_scene": "a", "start_bar": 5, "length_bars": 8},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr), "--strict"])

    assert rc == 1
    assert "should start at bar 1" in capsys.readouterr().err


def test_validate_strict_accepts_contiguous_arrangement(tmp_path: Path, capsys):
    # create-simple lays out a contiguous, bar-1-anchored arrangement.
    arr = tmp_path / "arr.json"
    main(["create-simple", "--name", "ok", "--out", str(arr)])
    capsys.readouterr()  # drop create-simple output

    rc = main(["validate", "--arrangement", str(arr), "--strict"])

    assert rc == 0
    assert "5 section" in capsys.readouterr().out


def test_validate_strict_json_carries_gap_error(tmp_path: Path, capsys):
    arr = _gapped(tmp_path / "gap.json")

    rc = main(["validate", "--arrangement", str(arr), "--strict", "--json"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["valid"] is False
    assert any("gap between" in err for err in payload["errors"])


# --- validate --json -------------------------------------------------------------

def test_validate_json_reports_valid_arrangement(tmp_path: Path, capsys):
    arr = tmp_path / "arr.json"
    main(["create-simple", "--name", "ok", "--out", str(arr)])
    capsys.readouterr()  # drop the create-simple output so stdout is JSON only

    rc = main(["validate", "--arrangement", str(arr), "--json"])

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""  # machine-readable result goes to stdout only
    payload = json.loads(captured.out)
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert payload["name"] == "ok"
    assert payload["section_count"] == 5
    assert isinstance(payload["total_bars"], int)


def test_validate_json_reports_errors_for_invalid_arrangement(tmp_path: Path, capsys):
    arr = _write(
        tmp_path / "dup.json",
        {
            "name": "dup",
            "sections": [
                {"section_id": "x", "name": "A", "source_scene": "a", "start_bar": 1, "length_bars": 8},
                {"section_id": "x", "name": "B", "source_scene": "b", "start_bar": 9, "length_bars": 8},
            ],
        },
    )

    rc = main(["validate", "--arrangement", str(arr), "--json"])

    assert rc == 1
    captured = capsys.readouterr()
    # Errors are carried inside the JSON payload, not printed to stderr.
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["valid"] is False
    assert payload["name"] == "dup"
    assert payload["section_count"] == 2
    assert any("duplicate section_id" in err for err in payload["errors"])


def test_validate_json_reports_unreadable_document(tmp_path: Path, capsys):
    missing = tmp_path / "nope.json"

    rc = main(["validate", "--arrangement", str(missing), "--json"])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["valid"] is False
    # No plan could be built, so the summary fields are null and the error is present.
    assert payload["name"] is None
    assert payload["section_count"] is None
    assert payload["total_bars"] is None
    assert payload["errors"]


# --- parent directories & parser -------------------------------------------------

def test_create_simple_makes_missing_parent_directories(tmp_path: Path):
    out = tmp_path / "nested" / "deep" / "arr.json"

    rc = main(["create-simple", "--name", "demo", "--out", str(out)])

    assert rc == 0
    assert out.exists()


def test_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main([])
