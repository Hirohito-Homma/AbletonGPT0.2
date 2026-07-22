"""Tests for backend selection in the MCP server.

``select_backend`` picks the Remote Script (default) or the Ableton Extensions SDK
companion based on the ``backend`` config value / ``ABLETONGPT_BACKEND`` env var. Both
share the ``call`` contract, so the tool surface is unchanged. Selecting a backend must
not open any socket (connections are lazy).
"""

from __future__ import annotations

import pytest

from abletongpt import server
from abletongpt.bridge import AbletonBridge
from abletongpt.extensions_bridge import ExtensionsBridge


@pytest.fixture(autouse=True)
def clear_backend_env(monkeypatch):
    monkeypatch.delenv("ABLETONGPT_BACKEND", raising=False)


def test_default_backend_is_remote_script(monkeypatch):
    monkeypatch.setattr(server, "setting", lambda name, default, *a, **k: default)

    assert server.resolve_backend_name() == "remote_script"
    assert isinstance(server.select_backend(), AbletonBridge)


def test_env_selects_extensions_backend(monkeypatch):
    monkeypatch.setenv("ABLETONGPT_BACKEND", "extensions")

    assert server.resolve_backend_name() == "extensions"
    assert isinstance(server.select_backend(), ExtensionsBridge)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("remote_script", "remote_script"),
        ("remote", "remote_script"),
        ("default", "remote_script"),
        ("Extensions", "extensions"),
        ("extension", "extensions"),
        ("  extensions  ", "extensions"),
        ("auto", "auto"),
        ("AUTO", "auto"),
    ],
)
def test_aliases_and_normalization(monkeypatch, value, expected):
    monkeypatch.setenv("ABLETONGPT_BACKEND", value)

    assert server.resolve_backend_name() == expected


def test_unknown_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("ABLETONGPT_BACKEND", "midi_yoke")

    with pytest.raises(ValueError):
        server.resolve_backend_name()


def test_auto_backend_builds_a_fallback_bridge(monkeypatch):
    from abletongpt.backends import FallbackBridge

    monkeypatch.setenv("ABLETONGPT_BACKEND", "auto")

    assert server.resolve_backend_name() == "auto"
    assert isinstance(server.select_backend(), FallbackBridge)


def test_capabilities_report_active_backend(monkeypatch):
    monkeypatch.setenv("ABLETONGPT_BACKEND", "extensions")

    caps = server.get_abletongpt_capabilities()
    assert caps["backend"] == "extensions"
    assert caps["available_backends"] == ["remote_script", "extensions", "auto"]


def test_capabilities_does_not_probe_for_auto(monkeypatch):
    # Reporting capabilities must not open a socket, even in auto mode.
    monkeypatch.setenv("ABLETONGPT_BACKEND", "auto")

    caps = server.get_abletongpt_capabilities()
    assert caps["backend"] == "auto"
