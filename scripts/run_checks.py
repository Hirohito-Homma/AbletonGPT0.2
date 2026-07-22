#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


def main() -> None:
    failures = []
    test_namespace = runpy.run_path(str(ROOT / "tests" / "test_bridge.py"))
    tests = sorted(
        (name, function)
        for name, function in test_namespace.items()
        if name.startswith("test_") and callable(function)
    )
    for name, function in tests:
        try:
            function()
            print("PASS %s" % name)
        except Exception as exc:
            failures.append((name, exc))
            print("FAIL %s: %s" % (name, exc))

    for module_name in (
        "abletongpt.arrange.presets",
        "abletongpt.audio",
        "abletongpt.backends",
        "abletongpt.bridge",
        "abletongpt.cli.arrange",
        "abletongpt.cli.audio",
        "abletongpt.cli.compose",
        "abletongpt.cli.contextual",
        "abletongpt.cli.expression",
        "abletongpt.cli.instruments",
        "abletongpt.cli.jobs",
        "abletongpt.cli.main",
        "abletongpt.cli.serialization",
        "abletongpt.cli.vocal",
        "abletongpt.composition",
        "abletongpt.config",
        "abletongpt.cli.loudness",
        "abletongpt.contextual",
        "abletongpt.doctor",
        "abletongpt.expression",
        "abletongpt.extensions_bridge",
        "abletongpt.harmony",
        "abletongpt.instruments",
        "abletongpt.jobs",
        "abletongpt.jobs.executors",
        "abletongpt.jobs.runner",
        "abletongpt.jobs.store",
        "abletongpt.loudness",
        "abletongpt.meters",
        "abletongpt.reference",
        "abletongpt.server",
        "abletongpt.snapshots",
        "abletongpt.targets",
        "abletongpt.transcription",
        "abletongpt.vocal",
        "abletongpt.warp",
    ):
        try:
            __import__(module_name)
            print("PASS import %s" % module_name)
        except Exception as exc:
            failures.append(("import %s" % module_name, exc))
            print("FAIL import %s: %s" % (module_name, exc))

    if importlib.util.find_spec("mcp") is None:
        failures.append(("dependency mcp", RuntimeError("mcp package is missing")))
        print("FAIL dependency mcp: package is missing")
    else:
        print("PASS dependency mcp")

    print("\n%d checks, %d failures" % (len(tests) + 37, len(failures)))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
