from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any

from .config import load_config_file, setting


class ExtensionsConnectionError(RuntimeError):
    """Raised when the AbletonGPT Extension endpoint cannot be reached."""


@dataclass(frozen=True)
class ExtensionsBridgeConfig:
    """Connection settings for the Node.js Ableton Extension companion."""

    host: str = "127.0.0.1"
    port: int = 9878
    token: str = ""
    timeout: float = 3.0

    @classmethod
    def load(cls) -> "ExtensionsBridgeConfig":
        values = load_config_file()
        host = str(setting("extensions_host", "127.0.0.1", values))
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ableton Extensions bridge host must be localhost")
        return cls(
            host=host,
            port=int(setting("extensions_port", 9878, values)),
            token=str(setting("extensions_token", setting("token", "", values), values)),
            timeout=float(setting("extensions_timeout", 3.0, values)),
        )


class ExtensionsBridge:
    """Newline-delimited JSON client for an Ableton Extensions SDK companion.

    The official SDK-facing Node.js implementation lives under ``extensions/``.
    This Python class intentionally does not import SDK-specific packages, so the
    existing Remote Script integration remains usable on stable Live versions.
    """

    def __init__(self, config: ExtensionsBridgeConfig | None = None) -> None:
        self.config = config or ExtensionsBridgeConfig.load()

    def call(self, command: str, **params: Any) -> Any:
        request = {
            "protocol": "abletongpt.extensions.v1",
            "command": command,
            "params": params,
            "token": self.config.token,
        }
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")

        try:
            with socket.create_connection(
                (self.config.host, self.config.port), self.config.timeout
            ) as connection:
                connection.settimeout(self.config.timeout)
                connection.sendall(payload)
                response = self._read_line(connection)
        except (OSError, TimeoutError) as exc:
            raise ExtensionsConnectionError(
                "Ableton Extensionに接続できません。Live 12 Suite BetaとAbletonGPT Extensionを起動してください。"
            ) from exc

        try:
            decoded = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ExtensionsConnectionError("Ableton Extensionから不正な応答を受信しました。") from exc

        if decoded.get("protocol") not in {None, "abletongpt.extensions.v1"}:
            raise ExtensionsConnectionError("Ableton Extensionのプロトコル版が一致しません。")
        if not decoded.get("ok"):
            raise RuntimeError(decoded.get("error", "Ableton Extension command failed"))
        return decoded.get("result")

    @staticmethod
    def _read_line(connection: socket.socket) -> str:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > 1_000_000:
                raise ExtensionsConnectionError("Ableton Extensionからの応答が大きすぎます。")
            if b"\n" in chunk:
                break
        return b"".join(chunks).split(b"\n", 1)[0].decode("utf-8")
