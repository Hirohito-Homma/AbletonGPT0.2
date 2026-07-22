"""Command-line entry point for expressive editing of an existing MIDI clip.

    python -m abletongpt.cli.expression --clip clip.json --accent 0.6 --swing 0.4
    python -m abletongpt.cli.expression --clip clip.json --humanize 0.3 --seed 7 --json
    python -m abletongpt.cli.expression --clip clip.json --automation arch --automation-cc 11

``--clip`` points at a JSON file describing an existing MIDI clip -- a ``length_beats``
number and a ``notes`` list of ``{pitch, start_time, duration, velocity}`` objects (the
shape Live returns). This runs the deterministic :func:`abletongpt.expression.build_expression_plan`
engine (metric accents, swing, humanization, weak-beat probability) and prints the result.
It is pure and read-only: it never mutates the source clip and never touches Ableton.
``--json`` emits the full machine-readable plan.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..expression import AUTOMATION_SHAPES, build_expression_plan


def _read_clip(path: str) -> dict:
    """Read a MIDI-clip JSON file (raises ValueError/OSError on read/parse failure)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _print_plan(plan: dict, *, as_json: bool) -> None:
    """Print the expression plan as JSON or a human-readable summary."""
    if as_json:
        print(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False))
        return
    settings = plan["settings"]
    diff = plan["diff"]
    velocity = diff["velocity"]
    timing = diff["timing"]
    print(
        "source: %s  %g beats, %d notes"
        % (
            plan["source"].get("track") or "?",
            plan["source"]["length_beats"],
            plan["source"]["note_count"],
        )
    )
    print(
        "accent %g  swing %g  humanize %g  weak-prob %g  (grid %g, %d/bar, seed %d)"
        % (
            settings["accent"],
            settings["swing"],
            settings["humanize"],
            settings["weak_beat_probability"],
            settings["grid_beats"],
            settings["beats_per_bar"],
            settings["seed"],
        )
    )
    print(
        "velocity: %g -> %g (range %d-%d)   timing shift: max %g, avg %g beats"
        % (
            velocity["average_before"],
            velocity["average_after"],
            velocity["range_after"][0],
            velocity["range_after"][1],
            timing["max_shift_beats"],
            timing["average_shift_beats"],
        )
    )
    print("min probability after: %g" % diff["probability"]["minimum_after"])
    for envelope in plan["automation"]:
        print(
            "automation: CC%d %s  %s  %d points"
            % (
                envelope["controller"],
                envelope.get("controller_name") or "",
                envelope["shape"],
                envelope["point_count"],
            )
        )


def _cmd(args: argparse.Namespace) -> int:
    try:
        clip = _read_clip(args.clip)
        plan = build_expression_plan(
            clip,
            accent=args.accent,
            swing=args.swing,
            humanize=args.humanize,
            weak_beat_probability=args.weak_beat_probability,
            beats_per_bar=args.beats_per_bar,
            grid_beats=args.grid_beats,
            automation_shape=args.automation,
            automation_cc=args.automation_cc,
            automation_depth=args.automation_depth,
            automation_base=args.automation_base,
            automation_cycles=args.automation_cycles,
            automation_resolution_beats=args.automation_resolution,
            seed=args.seed,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Missing/invalid file, or a clip the engine rejects (no notes, bad length,
        # out-of-range setting) -> clean exit 2 rather than a traceback.
        print("expression: %s" % exc, file=sys.stderr)
        return 2
    _print_plan(plan, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.expression",
        description="Add expressive performance to an existing MIDI clip (no Ableton needed).",
    )
    parser.add_argument("--clip", required=True, help="Path to a MIDI-clip JSON file.")
    parser.add_argument(
        "--accent",
        type=float,
        default=0.0,
        help="Metric velocity accent 0.0-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--swing",
        type=float,
        default=0.0,
        help="Off-grid swing amount 0.0-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--humanize",
        type=float,
        default=0.0,
        help="Timing/velocity jitter 0.0-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--weak-beat-probability",
        type=float,
        default=1.0,
        dest="weak_beat_probability",
        help="Per-note probability for off-grid notes 0.0-1.0 (default: %(default)s).",
    )
    parser.add_argument(
        "--beats-per-bar",
        type=int,
        default=4,
        dest="beats_per_bar",
        help="Time-signature numerator 1-16 (default: %(default)s).",
    )
    parser.add_argument(
        "--grid-beats",
        type=float,
        default=0.5,
        dest="grid_beats",
        help="Swing/accent grid in beats, e.g. 0.5 for 8ths (default: %(default)s).",
    )
    parser.add_argument(
        "--automation",
        default=None,
        choices=list(AUTOMATION_SHAPES),
        help="Also emit a MIDI CC envelope of this shape (default: none).",
    )
    parser.add_argument(
        "--automation-cc",
        type=int,
        default=1,
        dest="automation_cc",
        help="MIDI CC controller number 0-127 (default: %(default)s = Mod Wheel).",
    )
    parser.add_argument(
        "--automation-depth",
        type=int,
        default=64,
        dest="automation_depth",
        help="Envelope depth above base, 0-127 (default: %(default)s).",
    )
    parser.add_argument(
        "--automation-base",
        type=int,
        default=0,
        dest="automation_base",
        help="Envelope base value, 0-127 (default: %(default)s).",
    )
    parser.add_argument(
        "--automation-cycles",
        type=int,
        default=1,
        dest="automation_cycles",
        help="Cycles across the clip for the sine shape, 1-64 (default: %(default)s).",
    )
    parser.add_argument(
        "--automation-resolution",
        type=float,
        default=0.25,
        dest="automation_resolution",
        help="Breakpoint spacing in beats (default: %(default)s).",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="Deterministic seed (default: %(default)s)."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the full plan as JSON."
    )
    parser.set_defaults(func=_cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 on an invalid request)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
