"""Tests for the read-only warp-alignment server tools.

Both tools are read-only. The NumPy onset detection is monkeypatched with a canned result,
and a fake bridge returns canned warp markers -- no socket, no Live process, no audio file.
"""

from __future__ import annotations

import pytest

from abletongpt import server


_WARP = {
    "track": "Drums",
    "track_index": 0,
    "clip_index": 0,
    "clip": "Loop",
    "is_audio_clip": True,
    "warping": True,
    "warp_mode": 0,
    "marker_count": 3,
    "markers": [
        {"beat_time": 0.0, "sample_time": 0.0},
        {"beat_time": 1.0, "sample_time": 0.5},
        {"beat_time": 2.0, "sample_time": 1.0},
    ],
    "read_only": True,
}
_ONSETS = {"onset_times": [0.01, 0.52, 1.0], "onsets": [{"strength": 1.0}] * 3}


class FakeBridge:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_clip_warp_markers":
            return dict(_WARP)
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture
def fake_bridge(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(server, "bridge", bridge)
    monkeypatch.setattr(server, "detect_onsets", lambda *args, **kwargs: dict(_ONSETS))
    return bridge


def test_get_clip_warp_markers_forwards_target(fake_bridge):
    result = server.get_clip_warp_markers(0, 0)

    assert result["marker_count"] == 3
    command, params = fake_bridge.calls[0]
    assert command == "get_clip_warp_markers"
    assert params == {"track_index": 0, "clip_index": 0}


def test_get_clip_warp_markers_rejects_negative_index(fake_bridge):
    with pytest.raises(ValueError):
        server.get_clip_warp_markers(-1, 0)
    assert fake_bridge.calls == []


def test_alignment_report_combines_warp_and_onsets(fake_bridge):
    report = server.analyze_clip_warp_alignment("loop.wav", 0, 0, tolerance_seconds=0.05)

    # Only the read command was issued -- read-only.
    assert [command for command, _ in fake_bridge.calls] == ["get_clip_warp_markers"]
    assert report["warp_marker_count"] == 3
    assert report["onset_count"] == 3
    assert report["markers_on_transient"] == 3  # markers at 0/0.5/1.0 vs onsets 0.01/0.52/1.0
    assert report["marker_alignment_ratio"] == 1.0
    assert report["clip"]["name"] == "Loop"
    assert report["file"] == "loop.wav"
