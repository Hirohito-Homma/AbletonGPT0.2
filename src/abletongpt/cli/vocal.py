"""Command-line entry point for planning an editable Vocal Guide from lyrics.

    python -m abletongpt.cli.vocal --title Neon --lyrics "la la shine on" \
        --genre pop --mood bright --key A --mode minor --tempo 120 --bars 8
    python -m abletongpt.cli.vocal ... --json

Pure planning: this maps lyrics onto a deterministic melody (via the composition engine)
and prints the resulting Vocal Guide -- a human summary, or the full plan with ``--json``.
It reads no files and never touches Ableton; rendering audio is a separate handoff.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..composition import GENRE_PROFILES, MOOD_PROGRESSIONS, PITCH_CLASSES, SCALES
from ..vocal import build_vocal_plan

#: Bar counts the composition engine accepts.
_BARS_CHOICES = (4, 8, 16, 32)
#: Number of vocal events shown in the human preview.
_PREVIEW_EVENTS = 6


def _print_plan(plan: dict, *, as_json: bool) -> None:
    """Print a vocal plan as JSON or a human-readable summary with an event preview."""
    if as_json:
        print(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False))
        return

    events = plan["vocal_events"]
    print(
        "title: %s  key: %s  tempo: %g  bars: %d  seed: %d"
        % (plan["title"], plan["key"], plan["tempo"], plan["bars"], plan["seed"])
    )
    print("language: %s   vocal events: %d" % (plan["language_hint"], len(events)))
    for event in events[:_PREVIEW_EVENTS]:
        print(
            "  %-8s pitch %-3d @ %6.2f  (%.2f)"
            % (event["lyric"], event["pitch"], event["start_time"], event["duration"])
        )
    if len(events) > _PREVIEW_EVENTS:
        print("  ... %d more" % (len(events) - _PREVIEW_EVENTS))


def _cmd_plan(args: argparse.Namespace) -> int:
    try:
        plan = build_vocal_plan(
            title=args.title,
            lyrics=args.lyrics,
            genre=args.genre,
            mood=args.mood,
            key=args.key,
            mode=args.mode,
            tempo=args.tempo,
            bars=args.bars,
            seed=args.seed,
            melody_density=args.density,
        )
    except ValueError as exc:
        # argparse choices reject bad enums; this guards the remaining engine rules
        # (empty lyrics, tempo/density range) with a clean message instead of a traceback.
        print("vocal: %s" % exc, file=sys.stderr)
        return 2
    _print_plan(plan, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.vocal",
        description="Plan an editable Vocal Guide melody from lyrics (no Ableton needed).",
    )
    parser.add_argument("--title", required=True, help="Song/guide title.")
    parser.add_argument("--lyrics", required=True, help="Lyrics text to map onto notes.")
    parser.add_argument(
        "--genre", required=True, choices=sorted(GENRE_PROFILES), help="Musical genre."
    )
    parser.add_argument(
        "--mood", required=True, choices=sorted(MOOD_PROGRESSIONS), help="Overall mood."
    )
    parser.add_argument(
        "--key", required=True, choices=sorted(PITCH_CLASSES), help="Musical key root."
    )
    parser.add_argument(
        "--mode", required=True, choices=sorted(SCALES), help="Scale mode."
    )
    parser.add_argument(
        "--tempo", required=True, type=float, metavar="BPM", help="Tempo (40-240)."
    )
    parser.add_argument(
        "--bars",
        required=True,
        type=int,
        choices=_BARS_CHOICES,
        help="Number of bars.",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="Deterministic seed (default: %(default)s)."
    )
    parser.add_argument(
        "--density",
        type=float,
        default=0.7,
        metavar="D",
        help="Melody density 0.05-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full vocal plan as machine-readable JSON on stdout.",
    )
    parser.set_defaults(func=_cmd_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 on an invalid request)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
