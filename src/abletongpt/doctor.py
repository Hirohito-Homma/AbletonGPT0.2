from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bridge import BridgeConfig
from .config import default_config_path


def remote_script_path() -> Path | None:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Music"
            / "Ableton"
            / "User Library"
            / "Remote Scripts"
            / "AbletonGPT_MCP"
            / "__init__.py"
        )
    if sys.platform == "win32":
        return (
            Path.home()
            / "Documents"
            / "Ableton"
            / "User Library"
            / "Remote Scripts"
            / "AbletonGPT_MCP"
            / "__init__.py"
        )
    return None


def run_checks(connect: bool = True) -> dict[str, Any]:
    config_path = default_config_path()
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "python",
            "ok": sys.version_info >= (3, 11),
            "detail": platform.python_version(),
        }
    )
    checks.append(
        {
            "name": "config",
            "ok": config_path.is_file(),
            "detail": str(config_path),
        }
    )
    script_path = remote_script_path()
    checks.append(
        {
            "name": "remote_script",
            "ok": bool(script_path and script_path.is_file()),
            "detail": str(script_path) if script_path else "unsupported platform",
        }
    )
    try:
        bridge = BridgeConfig.load()
        bridge_detail = {**asdict(bridge), "token": "configured" if bridge.token else "empty"}
        bridge_ok = bridge.host in {"127.0.0.1", "localhost", "::1"}
    except Exception as exc:
        bridge = BridgeConfig()
        bridge_detail = {"error": str(exc)}
        bridge_ok = False
    checks.append({"name": "bridge_config", "ok": bridge_ok, "detail": bridge_detail})

    if connect:
        try:
            with socket.create_connection((bridge.host, bridge.port), min(bridge.timeout, 1.0)):
                connected = True
                detail = "%s:%d" % (bridge.host, bridge.port)
        except OSError as exc:
            connected = False
            detail = "%s（Live起動・Control Surface選択後に再確認）" % exc
        checks.append({"name": "ableton_connection", "ok": connected, "detail": detail})
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="AbletonGPTの導入状態を診断します")
    parser.add_argument("--json", action="store_true", help="JSONで表示")
    parser.add_argument("--no-connect", action="store_true", help="Liveへの接続確認を省略")
    args = parser.parse_args()
    result = run_checks(connect=not args.no_connect)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for check in result["checks"]:
            mark = "OK" if check["ok"] else "NG"
            print("[%s] %s: %s" % (mark, check["name"], check["detail"]))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
