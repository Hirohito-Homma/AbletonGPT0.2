"""Test the compare_live_meter_to_target server tool.

Read-only: it samples the master's momentary meter over a short window and compares peaks to a
built-in target's true-peak ceiling. A fake bridge feeds canned meter levels and time.sleep is
stubbed out -- no socket, no Live process, no real waiting.
"""

from __future__ import annotations

import pytest

from abletongpt import server


class FakeBridge:
    def __init__(self, levels):
        self._levels = list(levels)
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if command == "get_mix_snapshot":
            level = self._levels.pop(0) if self._levels else None
            return {"master": {"index": -1, "output_meter_level": level}}
        raise AssertionError("unexpected bridge command: %s" % command)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda *_a, **_k: None)


def test_samples_window_and_reports_headroom(monkeypatch):
    bridge = FakeBridge([0.4, 0.5, 0.45])
    monkeypatch.setattr(server, "bridge", bridge)

    report = server.compare_live_meter_to_target("streaming", seconds=0.3, interval=0.1)

    # 0.3s / 0.1s -> 3 samples, one get_mix_snapshot each.
    assert [command for command, _ in bridge.calls] == ["get_mix_snapshot"] * 3
    assert report["read_only"] is True
    assert report["target"]["name"] == "streaming"
    assert report["meter"]["samples"] == 3
    assert report["peak_headroom_db"] is not None


def test_over_ceiling_is_flagged(monkeypatch):
    monkeypatch.setattr(server, "bridge", FakeBridge([1.0, 1.0]))

    report = server.compare_live_meter_to_target("edm", seconds=0.2, interval=0.1)

    assert report["peak_headroom_db"] == -1.0  # 0 dBFS vs -1.0 dBTP ceiling
    assert any("above the" in note for note in report["guidance"])


def test_missing_meter_reports_cleanly(monkeypatch):
    # Extensions backend / stopped transport: meter comes back null.
    monkeypatch.setattr(server, "bridge", FakeBridge([None, None]))

    report = server.compare_live_meter_to_target("rock", seconds=0.2, interval=0.1)

    assert report["meter"] is None
    assert any("No meter reading" in note for note in report["guidance"])


def test_unknown_target_short_circuits_before_sampling(monkeypatch):
    bridge = FakeBridge([0.5])
    monkeypatch.setattr(server, "bridge", bridge)

    result = server.compare_live_meter_to_target("dubstep")

    assert "dubstep" in result["error"]
    assert bridge.calls == []  # never touched the bridge
    assert {row["name"] for row in result["targets"]}
