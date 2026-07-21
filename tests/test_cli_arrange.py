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


# --- parent directories & parser -------------------------------------------------

def test_create_simple_makes_missing_parent_directories(tmp_path: Path):
    out = tmp_path / "nested" / "deep" / "arr.json"

    rc = main(["create-simple", "--name", "demo", "--out", str(out)])

    assert rc == 0
    assert out.exists()


def test_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main([])
