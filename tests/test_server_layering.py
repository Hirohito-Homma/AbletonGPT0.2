"""Tests for the plan_section_layers / apply_section_layer MCP tools (no Live)."""

from __future__ import annotations

import pytest

from abletongpt import server


_STATE = {
    "tempo": 120.0,
    "tracks": [
        {"index": 0, "name": "Kick", "mute": False},
        {"index": 1, "name": "Bass", "mute": False},
        {"index": 2, "name": "Piano", "mute": False},
        {"index": 3, "name": "Pad", "mute": False},
    ],
}


class FakeBridge:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.mutes: dict[int, bool] = {}

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_state":
            return {"tracks": [dict(t) for t in _STATE["tracks"]]}
        if command == "set_track_mute":
            self.mutes[params["track_index"]] = params["muted"]
            return {"track_index": params["track_index"], "muted": params["muted"]}
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_plan_is_read_only(fake_bridge):
    plan = server.plan_section_layers(["Intro", "Chorus"])

    assert plan["read_only"] is True
    assert [command for command, _ in fake_bridge.calls] == ["get_state"]
    intro = plan["sections"][0]
    assert set(intro["active_tracks"]) == {"Piano", "Pad"}


def test_apply_sets_mutes_for_the_intro(fake_bridge):
    result = server.apply_section_layer(["Intro", "Chorus"], section_index=0)

    # Intro plays chords + pad; drums/bass muted.
    assert fake_bridge.mutes == {0: True, 1: True, 2: False, 3: False}
    assert set(result["muted_tracks"]) == {"Kick", "Bass"}
    assert set(result["unmuted_tracks"]) == {"Piano", "Pad"}
    # One set_track_mute per track.
    assert sum(1 for command, _ in fake_bridge.calls if command == "set_track_mute") == 4


def test_apply_full_chorus_unmutes_everything(fake_bridge):
    server.apply_section_layer(["Intro", "Chorus"], section_index=1)
    assert all(muted is False for muted in fake_bridge.mutes.values())


def test_role_override_applies(fake_bridge):
    # Force the Piano track to be treated as drums -> muted in the intro.
    server.apply_section_layer(["Intro"], section_index=0, track_roles=["drums", "bass", "drums", "pad"])
    assert fake_bridge.mutes[2] is True  # Piano-as-drums muted in the sparse intro


def test_role_override_length_mismatch_errors(fake_bridge):
    with pytest.raises(ValueError, match="track_roles"):
        server.plan_section_layers(["Intro"], track_roles=["drums"])  # 1 vs 4 tracks


def test_section_index_out_of_range_errors(fake_bridge):
    with pytest.raises(ValueError, match="section_index"):
        server.apply_section_layer(["Intro"], section_index=5)
