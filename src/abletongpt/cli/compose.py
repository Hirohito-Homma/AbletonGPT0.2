"""Command-line entry point for generating a deterministic multi-track song sketch.

    python -m abletongpt.cli.compose --title Demo --genre pop --mood bright \
        --key C --mode major --tempo 120 --bars 8
    python -m abletongpt.cli.compose ... --complexity seventh --seed 7 --json

Pure generation: this runs the deterministic :func:`abletongpt.composition.build_song_plan`
engine (chords / bass / melody / drums) and prints the result -- a human summary, or the
full plan as JSON with ``--json``. It reads no files and never touches Ableton.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..composition import (
    CHORD_SIZES,
    GENRE_PROFILES,
    MOOD_PROGRESSIONS,
    PITCH_CLASSES,
    SCALES,
    build_song_plan,
)

#: Bar counts the composition engine accepts.
_BARS_CHOICES = (4, 8, 16, 32)


def _print_plan(plan: dict, *, as_json: bool) -> None:
    """Print a song plan as JSON or a human-readable summary."""
    if as_json:
        print(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False))
        return

    settings = plan["professional_settings"]
    print(
        "title: %s  key: %s %s  tempo: %g  bars: %d  seed: %d"
        % (
            plan["title"],
            plan["key"],
            plan["mode"],
            plan["tempo"],
            plan["bars"],
            settings["seed"],
        )
    )
    print(
        "progression: %s   (%s / %s, %s)"
        % (
            " ".join(plan["chord_roots"]),
            plan["genre"],
            plan["mood"],
            settings["chord_complexity"],
        )
    )
    print("tracks:")
    for track in plan["tracks"]:
        print("  %-8s %d notes" % (track["role"], len(track["notes"])))


def _cmd_compose(args: argparse.Namespace) -> int:
    try:
        plan = build_song_plan(
            args.title,
            args.genre,
            args.mood,
            args.key,
            args.mode,
            args.tempo,
            args.bars,
            chord_complexity=args.complexity,
            melody_density=args.density,
            swing=args.swing,
            humanize=args.humanize,
            seed=args.seed,
        )
    except ValueError as exc:
        # argparse choices reject bad enums; this guards the engine's numeric ranges
        # (tempo, density, swing, humanize) with a clean message instead of a traceback.
        print("compose: %s" % exc, file=sys.stderr)
        return 2
    _print_plan(plan, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.compose",
        description="Generate a deterministic multi-track song sketch (no Ableton needed).",
    )
    parser.add_argument("--title", required=True, help="Song title.")
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
        "--bars", required=True, type=int, choices=_BARS_CHOICES, help="Number of bars."
    )
    parser.add_argument(
        "--complexity",
        default="triad",
        choices=sorted(CHORD_SIZES),
        help="Chord complexity (default: %(default)s).",
    )
    parser.add_argument(
        "--density",
        type=float,
        default=0.75,
        metavar="D",
        help="Melody density 0.05-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--swing",
        type=float,
        default=0.0,
        metavar="S",
        help="Swing amount 0.0-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--humanize",
        type=float,
        default=0.0,
        metavar="H",
        help="Humanize amount 0.0-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="Deterministic seed (default: %(default)s)."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full song plan as machine-readable JSON on stdout.",
    )
    parser.set_defaults(func=_cmd_compose)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 on an invalid request)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
