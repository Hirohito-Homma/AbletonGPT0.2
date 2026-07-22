from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any

from .config import load_config_file, setting


class AbletonConnectionError(RuntimeError):
    """Raised when the Ableton Remote Script cannot be reached."""


@dataclass(frozen=True)
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 9877
    token: str = ""
    timeout: float = 3.0

    @classmethod
    def load(cls) -> "BridgeConfig":
        values = load_config_file()
        host = str(setting("host", "127.0.0.1", values))
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ableton bridge host must be localhost")
        return cls(
            host=host,
            port=int(setting("port", 9877, values)),
            token=str(setting("token", "", values)),
            timeout=float(setting("timeout", 3.0, values)),
        )


class AbletonBridge:
    def __init__(self, config: BridgeConfig | None = None) -> None:
        self.config = config or BridgeConfig.load()

    def call(self, command: str, **params: Any) -> Any:
        request = {
            "command": command,
            "params": params,
            "token": self.config.token,
        }
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode()
        try:
            with socket.create_connection(
                (self.config.host, self.config.port), self.config.timeout
            ) as connection:
                connection.settimeout(self.config.timeout)
                connection.sendall(payload)
                response = self._read_line(connection)
        except (OSError, TimeoutError) as exc:
            raise AbletonConnectionError(
                "Ableton Liveに接続できません。Liveを起動し、AbletonGPTをControl Surfaceに選択してください。"
            ) from exc

        try:
            decoded = json.loads(response)
        except json.JSONDecodeError as exc:
            raise AbletonConnectionError("Ableton Liveから不正な応答を受信しました。") from exc
        if not decoded.get("ok"):
            raise RuntimeError(decoded.get("error", "Ableton command failed"))
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
                raise AbletonConnectionError("Ableton Liveからの応答が大きすぎます。")
            if b"\n" in chunk:
                break
        return b"".join(chunks).split(b"\n", 1)[0].decode("utf-8")
