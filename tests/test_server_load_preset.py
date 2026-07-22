"""Tests for the ``load_browser_preset`` MCP tool (a mutation).

The tool validates its arguments, then forwards a single ``load_preset`` command to the
bridge. Invalid input must be rejected *before* the bridge is touched. A fake bridge stands
in for Ableton -- no socket, no Live process. (The additive-load safety guard itself lives
in the Remote Script, which needs a running Live to exercise.)
"""

from __future__ import annotations

import pytest

from abletongpt import server


_LOAD_RESPONSE = {
    "track": "Lead",
    "track_index": 1,
    "loaded": "Grand Piano",
    "category": "instruments",
    "path": ["Piano & Keys"],
    "uri": "query:Instruments#Grand%20Piano",
    "device_count_before": 0,
    "device_count_after": 1,
    "added_device_count": 1,
    "devices": ["Grand Piano"],
    "verified_single_add": True,
}


class FakeBridge:
    """Returns a canned load result for ``load_preset`` and records every call."""

    def __init__(self, response=_LOAD_RESPONSE):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "load_preset":
            return dict(self._response)
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_load_forwards_target_and_defaults(fake_bridge):
    result = server.load_browser_preset(1, "instruments", "Grand Piano")

    assert result["verified_single_add"] is True
    command, params = fake_bridge.calls[0]
    assert command == "load_preset"
    assert params == {"track_index": 1, "category": "instruments", "path": [], "name": "Grand Piano"}


def test_load_forwards_path_and_strips_name(fake_bridge):
    server.load_browser_preset(2, "drums", "  808 Kit  ", path=["Kits"])

    _command, params = fake_bridge.calls[0]
    assert params == {"track_index": 2, "category": "drums", "path": ["Kits"], "name": "808 Kit"}


def test_load_rejects_negative_track_index(fake_bridge):
    with pytest.raises(ValueError):
        server.load_browser_preset(-1, "instruments", "Grand Piano")
    assert fake_bridge.calls == []


def test_load_rejects_unknown_category(fake_bridge):
    with pytest.raises(ValueError):
        server.load_browser_preset(0, "wavetables", "Grand Piano")
    assert fake_bridge.calls == []


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 301])
def test_load_rejects_bad_name(fake_bridge, bad_name):
    with pytest.raises(ValueError):
        server.load_browser_preset(0, "instruments", bad_name)
    assert fake_bridge.calls == []


def test_load_rejects_non_string_path(fake_bridge):
    with pytest.raises(ValueError):
        server.load_browser_preset(0, "instruments", "Grand Piano", path=["ok", 2])
    assert fake_bridge.calls == []


def test_load_issues_exactly_one_mutation_command(fake_bridge):
    server.load_browser_preset(0, "sounds", "Warm Pad")

    assert [command for command, _ in fake_bridge.calls] == ["load_preset"]
