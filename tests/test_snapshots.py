"""Tests for non-destructive state snapshots (pure logic, no Live, no NumPy)."""

from __future__ import annotations

from abletongpt.snapshots import SNAPSHOT_VERSION, build_snapshot, diff_snapshots


def _state():
    return {
        "is_playing": False,
        "tempo": 120.0,
        "signature": [4, 4],
        "scene_count": 8,
        "tracks": [
            {"index": 0, "name": "Drums", "arm": True, "clip_slots": 8},
            {"index": 1, "name": "Bass", "arm": False, "clip_slots": 8},
        ],
    }


def _mix():
    return {
        "tracks": [
            {
                "index": 0,
                "name": "Drums",
                "volume": 0.85,
                "pan": 0.0,
                "mute": False,
                "solo": False,
                "output_meter_level": 0.42,
                "sends": [{"index": 0, "value": 0.0}],
            },
            {
                "index": 1,
                "name": "Bass",
                "volume": 0.70,
                "pan": -0.2,
                "mute": False,
                "solo": False,
                "output_meter_level": 0.31,
                "sends": [{"index": 0, "value": 0.1}],
            },
        ],
        "returns": [
            {
                "index": 0,
                "name": "A-Reverb",
                "volume": 0.5,
                "pan": 0.0,
                "mute": False,
                "solo": False,
                "output_meter_level": 0.0,
                "sends": [],
            }
        ],
        "master": {
            "index": -1,
            "name": "Master",
            "volume": 0.9,
            "pan": 0.0,
            "mute": False,
            "solo": False,
            "output_meter_level": 0.5,
            "sends": [],
        },
        "meter_note": "momentary",
    }


def test_build_snapshot_shape_and_merge():
    snapshot = build_snapshot(_state(), _mix(), label="before edit", captured_at="2026-07-22T00:00:00+00:00")

    assert snapshot["read_only"] is True
    assert snapshot["snapshot_version"] == SNAPSHOT_VERSION
    assert snapshot["label"] == "before edit"
    assert snapshot["captured_at"] == "2026-07-22T00:00:00+00:00"
    assert snapshot["transport"] == {"tempo": 120.0, "signature": [4, 4], "scene_count": 8}
    assert snapshot["tracks"][0]["arm"] is True  # merged from get_state
    assert snapshot["tracks"][0]["clip_slots"] == 8
    assert snapshot["tracks"][1]["pan"] == -0.2  # from mix
    assert snapshot["master"]["name"] == "Master"
    assert len(snapshot["returns"]) == 1


def test_build_snapshot_excludes_momentary_meter():
    snapshot = build_snapshot(_state(), _mix())

    for channel in snapshot["tracks"] + snapshot["returns"] + [snapshot["master"]]:
        assert "output_meter_level" not in channel


def test_diff_reports_no_change_for_identical_snapshots():
    snapshot = build_snapshot(_state(), _mix(), captured_at="t0")
    # Same underlying state but different meter readings must still diff as unchanged.
    later_mix = _mix()
    later_mix["tracks"][0]["output_meter_level"] = 0.99
    later = build_snapshot(_state(), later_mix, captured_at="t1")

    diff = diff_snapshots(snapshot, later)

    assert diff["changed"] is False
    assert diff["transport"] == {}
    assert diff["tracks"] == {"changed": [], "added": [], "removed": []}


def test_diff_detects_mix_and_transport_changes():
    before = build_snapshot(_state(), _mix())
    after_state = _state()
    after_state["tempo"] = 128.0
    after_mix = _mix()
    after_mix["tracks"][0]["volume"] = 0.60
    after_mix["tracks"][1]["mute"] = True
    after_mix["tracks"][1]["sends"][0]["value"] = 0.4
    after = build_snapshot(after_state, after_mix)

    diff = diff_snapshots(before, after)

    assert diff["changed"] is True
    assert diff["transport"]["tempo"] == {"before": 120.0, "after": 128.0}
    changed = {entry["index"]: entry["changes"] for entry in diff["tracks"]["changed"]}
    assert changed[0]["volume"] == {"before": 0.85, "after": 0.60}
    assert changed[1]["mute"] == {"before": False, "after": True}
    assert changed[1]["sends"] == [{"index": 0, "before": 0.1, "after": 0.4}]


def test_diff_detects_added_and_removed_tracks():
    before = build_snapshot(_state(), _mix())
    after_state = _state()
    after_state["tracks"].append({"index": 2, "name": "Lead", "arm": False, "clip_slots": 8})
    after_mix = _mix()
    after_mix["tracks"].append(
        {"index": 2, "name": "Lead", "volume": 0.8, "pan": 0.0, "mute": False, "solo": False, "sends": []}
    )
    removed_state = _state()
    del removed_state["tracks"][1]
    removed_mix = _mix()
    del removed_mix["tracks"][1]

    added_diff = diff_snapshots(before, build_snapshot(after_state, after_mix))
    removed_diff = diff_snapshots(before, build_snapshot(removed_state, removed_mix))

    assert added_diff["tracks"]["added"] == [{"index": 2, "name": "Lead"}]
    assert removed_diff["tracks"]["removed"] == [{"index": 1, "name": "Bass"}]


def test_diff_ignores_sub_tolerance_float_noise():
    before = build_snapshot(_state(), _mix())
    after_mix = _mix()
    after_mix["tracks"][0]["volume"] = 0.85 + 1e-9  # below tolerance
    after = build_snapshot(_state(), after_mix)

    assert diff_snapshots(before, after)["changed"] is False
