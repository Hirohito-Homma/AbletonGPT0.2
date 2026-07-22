from __future__ import annotations

import json
import socket
import threading

import pytest

from abletongpt.extensions_bridge import (
    ExtensionsBridge,
    ExtensionsBridgeConfig,
    ExtensionsConnectionError,
)


def _serve_once(response: dict[str, object]) -> tuple[int, list[dict[str, object]], threading.Thread]:
    received: list[dict[str, object]] = []
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def run() -> None:
        try:
            connection, _ = server.accept()
            with connection:
                data = b""
                while b"\n" not in data:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                received.append(json.loads(data.split(b"\n", 1)[0]))
                connection.sendall((json.dumps(response) + "\n").encode("utf-8"))
        finally:
            server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return port, received, thread


def test_extensions_bridge_round_trip() -> None:
    port, received, thread = _serve_once(
        {
            "protocol": "abletongpt.extensions.v1",
            "ok": True,
            "result": {"tempo": 120},
        }
    )
    bridge = ExtensionsBridge(
        ExtensionsBridgeConfig(port=port, token="secret", timeout=1.0)
    )

    assert bridge.call("get_tempo", _timeout=2.0) == {"tempo": 120}
    thread.join(timeout=1.0)
    assert received == [
        {
            "protocol": "abletongpt.extensions.v1",
            "command": "get_tempo",
            "params": {},
            "token": "secret",
        }
    ]


def test_extensions_bridge_rejects_remote_host() -> None:
    with pytest.raises(ValueError, match="localhost"):
        ExtensionsBridgeConfig(host="example.com")


def test_extensions_bridge_reports_connection_failure() -> None:
    bridge = ExtensionsBridge(
        ExtensionsBridgeConfig(port=1, timeout=0.05)
    )
    with pytest.raises(ExtensionsConnectionError):
        bridge.call("ping")
