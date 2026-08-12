"""Tests for the plan_narrative_arc MCP tool (pure passthrough, no Live)."""

from __future__ import annotations

import pytest

from abletongpt import server


class ExplodingBridge:
    """The narrative plan is read-only and must never touch the bridge."""

    def call(self, command: str, **params):
        raise AssertionError("plan_narrative_arc must not call the bridge (got %s)" % command)


@pytest.fixture
def no_bridge(monkeypatch):
    monkeypatch.setattr(server, "bridge", ExplodingBridge())


def test_plan_narrative_arc_is_read_only_and_bridge_free(no_bridge):
    arc = server.plan_narrative_arc(["Intro", "Verse", "Build", "Chorus", "Outro"])
    assert arc["read_only"] is True
    assert arc["section_count"] == 5
    assert arc["peak_label"] == "Chorus"
    assert len(arc["sections"]) == 5


def test_plan_narrative_arc_rejects_empty(no_bridge):
    with pytest.raises(ValueError):
        server.plan_narrative_arc([])
