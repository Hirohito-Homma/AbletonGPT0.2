"""Tests for the read-only ``get_arrangement_clips`` MCP tool.

The tool validates its argument, then forwards a single ``get_arrangement_clips``
command to the bridge. Invalid input must be rejected *before* the bridge is
touched. A fake bridge stands in for Ableton -- no socket, no Live process.
"""

from __future__ import annotations

import pytest

from abletongpt import server


_ARRANGEMENT_RESPONSE = {
    "track_index": 1,
    "track": "Lead",
    "clips": [
        {
            "index": 0,
            "name": "Intro",
            "start_time": 0.0,
            "end_time": 16.0,
            "length_beats": 16.0,
            "is_audio_clip": False,
            "is_midi_clip": True,
            "muted": False,
        }
    ],
    "clip_count": 1,
    "truncated": False,
    "read_only": True,
}


class FakeBridge:
    """Returns a canned arrangement listing and records every call."""

    def __init__(self, response=_ARRANGEMENT_RESPONSE):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_arrangement_clips":
            return dict(self._response)
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    return bridge


def test_get_arrangement_clips_forwards_track_index(fake_bridge):
    result = server.get_arrangement_clips(1)

    assert fake_bridge.calls == [("get_arrangement_clips", {"track_index": 1})]
    assert result["read_only"] is True
    assert result["clip_count"] == 1


def test_get_arrangement_clips_rejects_negative_track_index(fake_bridge):
    with pytest.raises(ValueError):
        server.get_arrangement_clips(-1)

    assert fake_bridge.calls == []
