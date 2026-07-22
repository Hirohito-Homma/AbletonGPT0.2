"""Tests for the read-only ``browse_device_presets`` MCP tool.

The tool validates its arguments, then forwards a single ``browse_presets`` read command to
the bridge. It must never issue a mutating command. A fake bridge stands in for Ableton --
no socket, no Live process.
"""

from __future__ import annotations

import pytest

from abletongpt import server


_BROWSE_RESPONSE = {
    "category": "instruments",
    "path": [],
    "items": [
        {"name": "Drift", "is_folder": False, "is_loadable": True, "is_device": True,
         "uri": "query:Instruments#Drift", "source": "core"},
        {"name": "Bass", "is_folder": True, "is_loadable": False, "is_device": False,
         "uri": None, "source": None},
    ],
    "item_count": 2,
    "truncated": False,
    "read_only": True,
}


class FakeBridge:
    """Returns a canned browser listing for ``browse_presets`` and records every call."""

    def __init__(self, response=_BROWSE_RESPONSE):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "browse_presets":
            return dict(self._response)
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_browse_forwards_category_and_defaults(fake_bridge):
    result = server.browse_device_presets("instruments")

    assert result["read_only"] is True
    command, params = fake_bridge.calls[0]
    assert command == "browse_presets"
    assert params == {"category": "instruments", "path": [], "max_items": 200}


def test_browse_forwards_path_and_max_items(fake_bridge):
    server.browse_device_presets("drums", path=["808 Core Kit"], max_items=50)

    _command, params = fake_bridge.calls[0]
    assert params == {"category": "drums", "path": ["808 Core Kit"], "max_items": 50}


def test_browse_rejects_unknown_category(fake_bridge):
    with pytest.raises(ValueError):
        server.browse_device_presets("wavetables")
    assert fake_bridge.calls == []  # rejected before touching the bridge


def test_browse_rejects_non_string_path(fake_bridge):
    with pytest.raises(ValueError):
        server.browse_device_presets("instruments", path=["ok", 3])
    assert fake_bridge.calls == []


@pytest.mark.parametrize("bad", [0, -1, 1001])
def test_browse_rejects_out_of_range_max_items(fake_bridge, bad):
    with pytest.raises(ValueError):
        server.browse_device_presets("instruments", max_items=bad)
    assert fake_bridge.calls == []


def test_browse_only_issues_read_command(fake_bridge):
    server.browse_device_presets("sounds")
    server.browse_device_presets("packs", path=["My Pack"])

    assert [command for command, _ in fake_bridge.calls] == ["browse_presets", "browse_presets"]
