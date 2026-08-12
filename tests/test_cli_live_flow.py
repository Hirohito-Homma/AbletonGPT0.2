from __future__ import annotations

from abletongpt.cli.live_flow import _print_result, _run_flow


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
    assert "[OK] track=1 role=bass devices=Operator" in out
    assert "[FAIL] track=2 role=melody devices=none" in out
    assert "Live refused the insert" in out
    assert "display_value" not in out
    assert len(out) < 400
