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
    tests = []
    for test_file in ("test_bridge.py", "test_remote_script_runtime.py"):
        test_namespace = runpy.run_path(str(ROOT / "tests" / test_file))
        tests.extend(
            ("%s::%s" % (test_file, name), function)
            for name, function in test_namespace.items()
            if name.startswith("test_") and callable(function)
        )
    tests.sort()
    for name, function in tests:
        try:
            function()
            print("PASS %s" % name)
        except Exception as exc:
            failures.append((name, exc))
            print("FAIL %s: %s" % (name, exc))

    for module_name in _IMPORT_CHECKS:
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

    # Counted, not remembered. Two branches each added a module and each bumped a
    # hardcoded total to the same number; merged, the printed count was one short
    # of the checks that actually ran.
    print(
        "\n%d checks, %d failures"
        % (len(tests) + len(_IMPORT_CHECKS) + _DEPENDENCY_CHECKS, len(failures))
    )
    raise SystemExit(1 if failures else 0)


#: Every module that must import on a base install. Add one here and nothing else
#: needs updating -- the printed total is derived from this tuple.
_IMPORT_CHECKS = (
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
        "abletongpt.cli.intent",
        "abletongpt.cli.jobs",
        "abletongpt.cli.live_flow",
        "abletongpt.cli.main",
        "abletongpt.cli.serialization",
        "abletongpt.cli.ui",
        "abletongpt.cli.vocal",
        "abletongpt.composition",
        "abletongpt.config",
        "abletongpt.cli.loudness",
        "abletongpt.contextual",
        "abletongpt.delivery",
        "abletongpt.develop",
        "abletongpt.doctor",
        "abletongpt.drumkits",
        "abletongpt.expression",
        "abletongpt.extensions_bridge",
        "abletongpt.groove",
        "abletongpt.harmony",
        "abletongpt.instruments",
        "abletongpt.jobs",
        "abletongpt.jobs.executors",
        "abletongpt.jobs.kihachi",
        "abletongpt.jobs.runner",
        "abletongpt.jobs.store",
        "abletongpt.jobs.tracks",
        "abletongpt.layering",
        "abletongpt.loudness",
        "abletongpt.meters",
        "abletongpt.narrative",
        "abletongpt.notelength",
        "abletongpt.phrase",
        "abletongpt.progression",
        "abletongpt.quantize",
        "abletongpt.reference",
        "abletongpt.remap",
        "abletongpt.reverse",
        "abletongpt.scale",
        "abletongpt.section_spectral",
        "abletongpt.server",
        "abletongpt.snapshots",
        "abletongpt.songspec",
        "abletongpt.targets",
        "abletongpt.timescale",
        "abletongpt.transcription",
        "abletongpt.transpose",
        "abletongpt.vocal",
        "abletongpt.warp",
)

#: The `mcp` dependency probe, which is not a module import.
_DEPENDENCY_CHECKS = 1


if __name__ == "__main__":
    main()
