"""Command-line entry point for offline audio-track feature extraction.

    python -m abletongpt.cli.audio tempo --file loop.wav
    python -m abletongpt.cli.audio tempo --file loop.wav --min-bpm 80 --max-bpm 160 --json

Read-only: measures the file and prints the result -- a human summary, or the full result
as JSON with ``--json``. It never writes or modifies the audio. Wraps the pure
:mod:`abletongpt.audio` engine, which needs the optional ``audio`` extra (NumPy);
install it with ``pip install abletongpt[audio]``. Subcommands grow as extractors are
added (``key`` etc.).
"""

from __future__ import annotations

import argparse
import json
import sys

from ..audio import AudioDependencyError, estimate_tempo


def _print_tempo(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "tempo: %g BPM  (confidence %.2f)   %g s @ %d Hz   range %g-%g   [%s]"
        % (
            result["tempo_bpm"],
            result["confidence"],
            result["duration_seconds"],
            result["sample_rate"],
            result["bpm_range"][0],
            result["bpm_range"][1],
            result["method"],
        )
    )


def _cmd_tempo(args: argparse.Namespace) -> int:
    try:
        result = estimate_tempo(args.file, min_bpm=args.min_bpm, max_bpm=args.max_bpm)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_tempo(result, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.audio",
        description="Offline audio-track feature extraction (no Ableton needed).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    tempo = sub.add_parser("tempo", help="Estimate the tempo (BPM) of an audio file.")
    tempo.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    tempo.add_argument(
        "--min-bpm", type=float, default=60.0, dest="min_bpm", help="Lowest BPM to consider."
    )
    tempo.add_argument(
        "--max-bpm", type=float, default=200.0, dest="max_bpm", help="Highest BPM to consider."
    )
    tempo.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    tempo.set_defaults(func=_cmd_tempo)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 bad request, 3 missing extra)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
