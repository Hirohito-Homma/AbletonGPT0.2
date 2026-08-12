from __future__ import annotations

import copy

import pytest

from abletongpt.jobs import InvalidKihachiPlan, build_kihachi_job_plan


def _document():
    return {
        "arrangement_plan_version": "0.1",
        "execution_state": "planned_not_applied",
        "song": {"title": "Dub Contract", "bpm": 110},
        "operations": [
            {"op": "set_tempo", "params": {"bpm": 110}},
            {
                "op": "create_track",
                "params": {
                    "track_type": "midi",
                    "name": "KIHACHI Chords",
                    "index": -1,
                },
            },
            {
                "op": "apply_live_instrument_selection",
                "params": {
                    "track_index": 0,
                    "role": "chords",
                    "genre": "edm",
                    "mood": "dark",
                },
            },
            {
                "op": "create_midi_clip",
                "params": {
                    "track_index": 0,
                    "clip_index": 0,
                    "name": "KIHACHI Chords (full)",
                    "length_beats": 8.0,
                    "notes": [
                        {
                            "pitch": 60,
                            "start_time": 0.0,
                            "duration": 1.0,
                            "velocity": 90,
                        }
                    ],
                },
            },
            {
                "op": "set_clip_send_envelope",
                "params": {
                    "track_index": 0,
                    "clip_index": 0,
                    "send_index": 1,
                    "steps": [
                        {"start": 0.0, "length": 4.0, "value": 0.1},
                        {"start": 4.0, "length": 4.0, "value": 0.42},
                    ],
                },
            },
            {
                "op": "copy_session_clip_to_arrangement",
                "params": {
                    "track_index": 0,
                    "clip_index": 0,
                    "destination_time_beats": 0.0,
                    "name": "KIHACHI Chords",
                },
            },
        ],
    }


def test_converts_the_core_contract_in_order_with_stable_ids():
    plan = build_kihachi_job_plan(_document())

    assert plan.name == "Dub Contract"
    assert plan.step_ids == (
        "0000_set_tempo",
        "0001_create_track",
        "0002_apply_live_instrument_selection",
        "0003_create_midi_clip",
        "0004_set_clip_send_envelope",
        "0005_copy_session_clip_to_arrangement",
    )
    assert [step.command for step in plan.steps] == [
        operation["op"] for operation in _document()["operations"]
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("arrangement_plan_version", "9.9", "unsupported"),
        ("execution_state", "applied", "planned_not_applied"),
        ("operations", [], "non-empty"),
    ],
)
def test_rejects_a_bad_document_contract(field, value, message):
    document = _document()
    document[field] = value

    with pytest.raises(InvalidKihachiPlan, match=message):
        build_kihachi_job_plan(document)


def test_rejects_non_core_operations_before_returning_a_plan():
    document = _document()
    document["operations"].append(
        {
            "op": "import_vocal_take",
            "params": {"file_path": "/tmp/take.wav"},
        }
    )

    with pytest.raises(InvalidKihachiPlan, match="import_vocal_take"):
        build_kihachi_job_plan(document)


def test_preflights_every_step_including_a_late_invalid_send():
    document = copy.deepcopy(_document())
    document["operations"][4]["params"]["steps"][1]["value"] = 1.1

    with pytest.raises(InvalidKihachiPlan, match="operation 4.*between 0.0 and 1.0"):
        build_kihachi_job_plan(document)


def test_rejects_an_unknown_instrument_role_during_pure_preflight():
    document = copy.deepcopy(_document())
    document["operations"][2]["params"]["role"] = "guitar"

    with pytest.raises(InvalidKihachiPlan, match="operation 2.*unsupported instrument role"):
        build_kihachi_job_plan(document)


def test_rejects_unexpected_params_instead_of_forwarding_them():
    document = copy.deepcopy(_document())
    document["operations"][1]["params"]["delete_existing"] = True

    with pytest.raises(InvalidKihachiPlan, match="unexpected parameter"):
        build_kihachi_job_plan(document)
