"""Tests for FallbackBridge, the ``auto`` backend's prefer-with-fallback router.

Safety is the point of these tests: a real command must reach exactly one backend, a
mutating command is never retried on the other backend, and only a connection failure
(never a command error) triggers the fallback.
"""

from __future__ import annotations

import pytest

from abletongpt.backends import FallbackBridge
from abletongpt.bridge import AbletonConnectionError
from abletongpt.extensions_bridge import ExtensionsConnectionError


class FakeBackend:
    """Records calls; can be made unreachable or made to fail a specific command."""

    def __init__(self, *, unreachable=False, fail_command=None, error=None):
        self.calls: list[tuple[str, dict]] = []
        self._unreachable = unreachable
        self._fail_command = fail_command
        self._error = error or RuntimeError("command failed")

    def call(self, command: str, **params):
        self.calls.append((command, params))
        if self._unreachable:
            raise ExtensionsConnectionError("companion not running")
        if command == self._fail_command:
            raise self._error
        return {"command": command, "params": params}

    @property
    def commands(self):
        return [command for command, _ in self.calls]


def test_uses_primary_when_reachable():
    primary, secondary = FakeBackend(), FakeBackend()
    bridge = FallbackBridge(primary, secondary)

    result = bridge.call("get_state")

    assert result["command"] == "get_state"
    assert "get_state" in primary.commands
    assert secondary.calls == []  # secondary never touched


def test_falls_back_to_secondary_when_primary_unreachable():
    primary = FakeBackend(unreachable=True)
    secondary = FakeBackend()
    bridge = FallbackBridge(primary, secondary)

    result = bridge.call("get_state")

    assert result["command"] == "get_state"
    # Primary only saw the probe; the real command went to the secondary.
    assert primary.commands == ["ping"]
    assert "get_state" in secondary.commands


def test_choice_is_sticky_and_probes_once():
    primary = FakeBackend(unreachable=True)
    secondary = FakeBackend()
    bridge = FallbackBridge(primary, secondary)

    bridge.call("get_state")
    bridge.call("set_tempo", bpm=120)
    bridge.call("get_state")

    # The primary is probed exactly once, never retried.
    assert primary.commands == ["ping"]
    assert secondary.commands == ["get_state", "set_tempo", "get_state"]


def test_mutating_command_is_never_sent_to_both_backends():
    # If the primary is reachable, the mutation goes only to the primary.
    primary, secondary = FakeBackend(), FakeBackend()
    bridge = FallbackBridge(primary, secondary)

    bridge.call("apply_expression_to_clip", track_index=0, clip_index=0, notes=[])

    assert "apply_expression_to_clip" in primary.commands
    assert secondary.calls == []


def test_command_error_propagates_without_fallback():
    # Primary is reachable but the command fails on Live -> must NOT retry on secondary.
    primary = FakeBackend(fail_command="apply_expression_to_clip",
                          error=RuntimeError("clip index out of range"))
    secondary = FakeBackend()
    bridge = FallbackBridge(primary, secondary)

    with pytest.raises(RuntimeError, match="clip index out of range"):
        bridge.call("apply_expression_to_clip", track_index=9, clip_index=9, notes=[])

    assert secondary.calls == []  # the failing command was never re-sent


def test_default_unreachable_covers_both_backend_connection_errors():
    for error in (AbletonConnectionError("x"), ExtensionsConnectionError("y")):
        primary = FakeBackend()
        primary._unreachable = False
        # Make the probe raise the specific connection error type.
        primary._fail_command = "ping"
        primary._error = error
        secondary = FakeBackend()
        bridge = FallbackBridge(primary, secondary)

        bridge.call("get_state")

        assert "get_state" in secondary.commands


def test_construction_opens_no_socket():
    # Neither the probe nor a connection happens until the first call.
    primary = FakeBackend(unreachable=True)
    secondary = FakeBackend()
    bridge = FallbackBridge(primary, secondary)

    assert bridge.is_resolved is False
    assert primary.calls == []
