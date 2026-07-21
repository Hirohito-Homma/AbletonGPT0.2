from __future__ import annotations

import json
from pathlib import Path

from abletongpt.arrange import ArrangeEngine
from abletongpt.jobs import (
    JobPlan,
    JobStep,
    StepStatus,
    build_job_plan,
    load_job_plan,
    load_step_statuses,
    save_job_plan,
)


def _default_job_plan() -> JobPlan:
    return build_job_plan(ArrangeEngine().dark_tech_house_default())


# --- round-trip ------------------------------------------------------------------

def test_saved_plan_round_trips_to_an_equal_plan(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "plan.json"

    save_job_plan(plan, path)
    loaded = load_job_plan(path)

    assert loaded == plan
    assert loaded.step_ids == plan.step_ids


def test_round_trip_preserves_step_command_and_params(tmp_path: Path):
    plan = JobPlan(
        name="custom",
        steps=(
            JobStep("00_a", "place_scene", {"source_scene": "intro", "start_bar": 0}),
            JobStep("01_b", "place_scene", {"source_scene": "drop", "length_bars": 16}),
        ),
    )
    path = tmp_path / "custom.json"

    save_job_plan(plan, path)
    loaded = load_job_plan(path)

    assert loaded == plan
    assert loaded.steps[1].params == {"source_scene": "drop", "length_bars": 16}


def test_empty_plan_round_trips(tmp_path: Path):
    plan = JobPlan(name="empty")
    path = tmp_path / "empty.json"

    save_job_plan(plan, path)
    loaded = load_job_plan(path)

    assert loaded == plan
    assert loaded.steps == ()


# --- status persistence ----------------------------------------------------------

def test_statuses_default_to_pending_when_not_provided(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "plan.json"

    save_job_plan(plan, path)
    statuses = load_step_statuses(path)

    assert set(statuses) == set(plan.step_ids)
    assert all(status is StepStatus.PENDING for status in statuses.values())


def test_completed_failed_and_pending_statuses_are_saved_and_restored(tmp_path: Path):
    plan = _default_job_plan()
    ids = plan.step_ids
    statuses = {
        ids[0]: StepStatus.SUCCEEDED,
        ids[1]: StepStatus.SKIPPED,
        ids[2]: StepStatus.FAILED,
        # remaining ids intentionally omitted -> should come back as PENDING
    }
    path = tmp_path / "progress.json"

    save_job_plan(plan, path, statuses=statuses)
    restored = load_step_statuses(path)

    assert restored[ids[0]] is StepStatus.SUCCEEDED
    assert restored[ids[1]] is StepStatus.SKIPPED
    assert restored[ids[2]] is StepStatus.FAILED
    assert restored[ids[3]] is StepStatus.PENDING
    # The plan itself is unaffected by the status overlay.
    assert load_job_plan(path) == plan


# --- path handling ---------------------------------------------------------------

def test_accepts_str_path(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "as_str.json"

    save_job_plan(plan, str(path))
    assert load_job_plan(str(path)) == plan


def test_creates_missing_parent_directories(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "nested" / "deeper" / "plan.json"
    assert not path.parent.exists()

    returned = save_job_plan(plan, path)

    assert returned == path
    assert path.exists()
    assert load_job_plan(path) == plan


def test_saved_file_is_valid_json_with_a_schema_version(tmp_path: Path):
    plan = _default_job_plan()
    path = tmp_path / "plan.json"

    save_job_plan(plan, path)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["name"] == plan.name
    assert document["schema_version"] == 1
    assert len(document["steps"]) == len(plan.steps)
    assert document["steps"][0]["status"] == "pending"
