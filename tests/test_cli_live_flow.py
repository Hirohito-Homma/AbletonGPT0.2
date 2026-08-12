from __future__ import annotations

import pytest

from abletongpt.cli.live_flow import _parse_into, _print_result, _run_flow


def test_run_flow_marks_success_when_tracks_report_live_devices(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_create_track(track_type: str, name: str = "", index: int = -1):
        calls.append(("create_track", {"track_type": track_type, "name": name, "index": index}))
        return {"index": len(calls) - 1}

    def fake_apply_instrument(track_index: int, role: str, genre: str, mood: str, **kwargs):
        calls.append(("apply_instrument", {"track_index": track_index, "role": role, "genre": genre, "mood": mood}))
        return {"ok": True, "track_index": track_index, "role": role}

    def fake_apply_drum_kit(track_index: int, genre: str, mood: str, role: str, **kwargs):
        calls.append(("apply_drum_kit", {"track_index": track_index, "genre": genre, "mood": mood, "role": role}))
        return {"ok": True, "track_index": track_index, "role": role}

    def fake_get_track_devices(track_index: int):
        calls.append(("get_track_devices", {"track_index": track_index}))
        if track_index == 0:
            return {"devices": ["Wavetable"]}
        if track_index == 1:
            return {"devices": ["Operator"]}
        return {"devices": ["909 Core Kit"]}

    monkeypatch.setattr("abletongpt.cli.live_flow.create_track", fake_create_track)
    monkeypatch.setattr("abletongpt.cli.live_flow.apply_live_instrument_selection", fake_apply_instrument)
    monkeypatch.setattr("abletongpt.cli.live_flow.apply_live_drum_kit", fake_apply_drum_kit)
    monkeypatch.setattr("abletongpt.cli.live_flow.get_track_devices", fake_get_track_devices)

    result = _run_flow(roles=["bass", "chords", "drums"], genre="tech_house", mood="dark")

    assert result["all_ok"] is True
    assert len(result["results"]) == 3
    assert [item["role"] for item in result["results"]] == ["bass", "chords", "drums"]
    assert all(item["ok"] for item in result["results"])


def test_summary_prints_device_names_not_the_parameter_dump(capsys):
    """A real ``get_track_devices`` entry carries every parameter of the device.

    Printing the raw list put ~40 KB per track on stdout against a running Live and
    buried the one thing the summary exists to show.
    """
    live_shaped_device = {
        "index": 0,
        "name": "Operator",
        "class_name": "Operator",
        "is_active": True,
        "parameters": [
            {"index": i, "name": "Param %d" % i, "value": 0.5, "display_value": "50 %"}
            for i in range(64)
        ],
    }
    result = {
        "genre": "tech_house",
        "mood": "dark",
        "roles": ["bass", "melody"],
        "all_ok": False,
        "results": [
            {"track_index": 1, "role": "bass", "name": "Bass", "ok": True, "devices": [live_shaped_device]},
            {"track_index": 2, "role": "melody", "name": "Melody", "ok": False, "error": "Live refused the insert"},
        ],
    }

    _print_result(result, as_json=False)

    out = capsys.readouterr().out
    assert "[OK] track=1 (new) role=bass devices=Operator" in out
    assert "[FAIL] track=2 (new) role=melody devices=none" in out
    assert "Live refused the insert" in out
    assert "display_value" not in out
    assert len(out) < 400


def test_into_reuses_the_named_track_and_creates_only_the_others(monkeypatch):
    created: list[str] = []
    inserted: list[int] = []

    def fake_create_track(track_type: str, name: str = "", index: int = -1):
        created.append(name)
        return {"index": 90 + len(created)}

    def fake_apply_instrument(track_index: int, role: str, genre: str, mood: str, **kwargs):
        inserted.append(track_index)
        return {"ok": True}

    def fake_apply_drum_kit(track_index: int, genre: str, mood: str, role: str, **kwargs):
        inserted.append(track_index)
        return {"ok": True}

    monkeypatch.setattr("abletongpt.cli.live_flow.create_track", fake_create_track)
    monkeypatch.setattr("abletongpt.cli.live_flow.apply_live_instrument_selection", fake_apply_instrument)
    monkeypatch.setattr("abletongpt.cli.live_flow.apply_live_drum_kit", fake_apply_drum_kit)
    monkeypatch.setattr(
        "abletongpt.cli.live_flow.get_track_devices",
        lambda track_index: {"devices": [{"name": "Operator"}]},
    )

    result = _run_flow(["bass", "chords"], genre="tech_house", mood="dark", into={"bass": 3})

    assert created == ["Chords"], "only the unmapped role may create a track"
    assert inserted == [3, 91]
    bass, chords = result["results"]
    assert bass["track_index"] == 3 and bass["created_track"] is False
    assert chords["created_track"] is True


def test_a_role_that_is_not_running_is_refused_rather_than_ignored(monkeypatch):
    """Ignoring it would create a new track for the role the caller redirected."""
    monkeypatch.setattr(
        "abletongpt.cli.live_flow.create_track",
        lambda **kwargs: pytest.fail("nothing may be created before the mapping is validated"),
    )

    with pytest.raises(ValueError, match="not being run"):
        _run_flow(["bass"], into={"drums": 2})


@pytest.mark.parametrize(
    "value",
    ["bass", "bass:", ":3", "bass:x", "bass:-1"],
)
def test_malformed_into_pairs_are_refused(value):
    with pytest.raises(ValueError):
        _parse_into([value])


def test_a_role_may_not_be_pointed_at_two_tracks():
    with pytest.raises(ValueError, match="twice"):
        _parse_into(["bass:1", "bass:2"])


def test_summary_says_whether_each_track_was_new_or_reused(capsys):
    _print_result(
        {
            "genre": "tech_house",
            "mood": "dark",
            "roles": ["bass", "chords"],
            "all_ok": True,
            "results": [
                {"track_index": 3, "role": "bass", "name": "Bass", "ok": True,
                 "created_track": False, "devices": [{"name": "Operator"}]},
                {"track_index": 9, "role": "chords", "name": "Chords", "ok": True,
                 "created_track": True, "devices": [{"name": "Analog"}]},
            ],
        },
        as_json=False,
    )

    out = capsys.readouterr().out
    assert "track=3 (existing) role=bass" in out
    assert "track=9 (new) role=chords" in out
