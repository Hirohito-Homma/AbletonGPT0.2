#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCRIPT = PROJECT_ROOT / "ableton_remote_script" / "AbletonGPT" / "__init__.py"
TARGET_DIR = (
    Path.home()
    / "Music"
    / "Ableton"
    / "User Library"
    / "Remote Scripts"
    / "AbletonGPT_MCP"
)
CONFIG_PATH = Path.home() / "Library" / "Application Support" / "AbletonGPT" / "config.json"


def install_remote_script(force: bool) -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    target = TARGET_DIR / "__init__.py"
    if target.exists() and target.read_bytes() != SOURCE_SCRIPT.read_bytes():
        if not force:
            raise RuntimeError(
                "%s は既存ファイルです。上書きする場合は --force を指定してください。" % target
            )
        backup = target.with_name("__init__.py.backup-%s" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(target, backup)
        print("既存Remote Scriptをバックアップしました: %s" % backup)
    shutil.copy2(SOURCE_SCRIPT, target)
    print("Remote Scriptを配置しました: %s" % target)


def ensure_config() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.is_file():
        try:
            values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            values = {}
    else:
        values = {}
    values.setdefault("host", "127.0.0.1")
    values.setdefault("port", 9877)
    values.setdefault("timeout", 3.0)
    values.setdefault("token", secrets.token_urlsafe(32))
    CONFIG_PATH.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)
    print("共有設定を作成しました: %s" % CONFIG_PATH)


def sync_python() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uvが見つかりません。https://docs.astral.sh/uv/ から導入してください。")
    subprocess.run([uv, "sync", "--extra", "dev"], cwd=PROJECT_ROOT, check=True)
    print("Python環境を準備しました: %s" % (PROJECT_ROOT / ".venv"))


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("このセットアップはmacOS専用です。Windowsではdocs/QUICKSTART_JA.mdを参照してください。")
    parser = argparse.ArgumentParser(description="AbletonGPT macOSセットアップ")
    parser.add_argument("--force", action="store_true", help="既存Remote Scriptをバックアップして更新")
    parser.add_argument("--skip-python", action="store_true", help="uv syncを省略")
    args = parser.parse_args()
    if not args.skip_python:
        sync_python()
    ensure_config()
    install_remote_script(force=args.force)
    executable = PROJECT_ROOT / ".venv" / "bin" / "abletongpt"
    print("\n次の手順:")
    print("1. Ableton Liveを完全に再起動")
    print("2. Settings > Link, Tempo & MIDI > Control Surface で AbletonGPT_MCP を選択")
    print("3. MCPコマンドとして登録: %s" % executable)
    print("4. 診断: %s" % (PROJECT_ROOT / ".venv" / "bin" / "abletongpt-doctor"))


if __name__ == "__main__":
    main()
