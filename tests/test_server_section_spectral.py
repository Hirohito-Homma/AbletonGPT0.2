"""Tests for the plan_section_spectral_balance MCP tool (pure passthrough, no Live)."""

from __future__ import annotations

import pytest

from abletongpt import server


class ExplodingBridge:
    """The spectral plan is report-only and must never touch the bridge."""

    def call(self, command: str, **params):
        raise AssertionError(
            "plan_section_spectral_balance must not call the bridge (got %s)" % command
        )


@pytest.fixture
def no_bridge(monkeypatch):
    monkeypatch.setattr(server, "bridge", ExplodingBridge())


def test_plan_is_report_only_and_bridge_free(no_bridge):
    plan = server.plan_section_spectral_balance(["Intro", "Verse", "Chorus", "Breakdown"])
    assert plan["read_only"] is True
    assert plan["section_count"] == 4
    chorus = next(s for s in plan["sections"] if s["archetype"] == "chorus")
    assert chorus["stereo"] == "wide"


def test_plan_rejects_empty(no_bridge):
    with pytest.raises(ValueError):
        server.plan_section_spectral_balance([])
