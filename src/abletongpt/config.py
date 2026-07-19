from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def default_config_path() -> Path:
    override = os.getenv("ABLETONGPT_CONFIG")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AbletonGPT" / "config.json"
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", str(Path.home())))
        return base / "AbletonGPT" / "config.json"
    base = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "abletongpt" / "config.json"


def load_config_file(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    if not config_path.is_file():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("AbletonGPTの設定ファイルを読み込めません: %s" % config_path) from exc
    if not isinstance(data, dict):
        raise ValueError("AbletonGPTの設定ファイルはJSONオブジェクトである必要があります")
    return data


def setting(name: str, default: Any, config: dict[str, Any] | None = None) -> Any:
    env_name = "ABLETONGPT_%s" % name.upper()
    if env_name in os.environ:
        return os.environ[env_name]
    values = config if config is not None else load_config_file()
    return values.get(name, default)

