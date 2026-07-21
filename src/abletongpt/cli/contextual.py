"""Command-line entry points for analyzing a MIDI clip and planning a complement.

    python -m abletongpt.cli.contextual analyze --clip clip.json
    python -m abletongpt.cli.contextual plan    --clip clip.json --target-role bass

``--clip`` points at a JSON file describing an existing MIDI clip -- at minimum a
``length_beats`` number and a ``notes`` list of ``{pitch, start_time, duration}`` objects
(the same shape ``get_midi_clip_notes`` returns from Live). Both commands are pure and
read-only: ``analyze`` infers musical context; ``plan`` designs a complementary part.
Neither touches Ableton, and ``--json`` emits the full machine-readable result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..composition import GENRE_PROFILES, MOOD_PROGRESSIONS
from ..contextual import (
    SOURCE_ROLES,
    TARGET_ROLES,
    analyze_midi_context,
    build_complementary_track_plan,
)


def _read_clip(path: str) -> dict:
    """Read a MIDI-clip JSON file (raises ValueError/OSError on read/parse failure)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _print_analysis(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    source = result["source"]
    context = result["musical_context"]
    print(
        "source: %s  role: %s (auto: %s)  length: %g beats"
        % (
            source.get("track_name") or "?",
            context["source_role"],
            context["auto_inferred_role"],
            source["length_beats"],
        )
    )
    key = context["key"]
    if key:
        print(
            "key: %s %s  (confidence %.2f, runner-up %s)"
            % (key["tonic"], key["mode"], key["confidence"], key["runner_up"])
        )
    else:
        print("key: n/a (drums)")
    pitch_range = context["pitch_range"]
    rhythm = context["rhythm"]
    print(
        "range: %d-%d (center %g)   rhythm: %g notes/bar, grid %g beats"
        % (
            pitch_range["lowest"],
            pitch_range["highest"],
            pitch_range["center"],
            rhythm["notes_per_bar"],
            rhythm["estimated_grid_beats"],
        )
    )
    for warning in result["warnings"]:
        print("  ! %s" % warning)


def _print_plan(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    track = result["target_track"]
    generation = result["generation"]
    instrument = result["instrument_selection"]
    print(
        "target: %s '%s'  %g beats, %d notes"
        % (track["role"], track["name"], track["length_beats"], len(track["notes"]))
    )
    print(
        "key: %s   instrument: %s"
        % (generation["key"], instrument.get("selected_instrument", "?"))
    )
    print("strategy: %s" % generation["strategy"])
    print("next: %s" % result["next_step"])


def _cmd_analyze(args: argparse.Namespace) -> int:
    try:
        clip = _read_clip(args.clip)
        result = analyze_midi_context(clip, source_role=args.source_role)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Missing/invalid file, or a clip the engine rejects (no notes, bad length) ->
        # clean exit 2 rather than a traceback. (JSONDecodeError is a ValueError.)
        print("contextual: %s" % exc, file=sys.stderr)
        return 2
    _print_analysis(result, as_json=args.json)
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    try:
        clip = _read_clip(args.clip)
        result = build_complementary_track_plan(
            clip,
            target_role=args.target_role,
            source_role=args.source_role,
            genre=args.genre,
            mood=args.mood,
            key_override=args.key,
            mode_override=args.mode,
            seed=args.seed,
            title=args.title,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("contextual: %s" % exc, file=sys.stderr)
        return 2
    _print_plan(result, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.contextual",
        description="Analyze a MIDI clip and plan a complementary part (no Ableton needed).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser(
        "analyze", help="Infer musical context (role, key, range, rhythm) from a clip."
    )
    analyze.add_argument("--clip", required=True, help="Path to a MIDI-clip JSON file.")
    analyze.add_argument(
        "--source-role",
        default="auto",
        choices=sorted(SOURCE_ROLES),
        help="Treat the source as this role (default: auto-infer).",
    )
    analyze.add_argument(
        "--json", action="store_true", help="Emit the full analysis as JSON."
    )
    analyze.set_defaults(func=_cmd_analyze)

    plan = sub.add_parser(
        "plan", help="Design a complementary track for the clip."
    )
    plan.add_argument("--clip", required=True, help="Path to a MIDI-clip JSON file.")
    plan.add_argument(
        "--target-role",
        required=True,
        choices=sorted(TARGET_ROLES),
        help="Role of the complementary part to generate.",
    )
    plan.add_argument(
        "--source-role",
        default="auto",
        choices=sorted(SOURCE_ROLES),
        help="Treat the source as this role (default: auto-infer).",
    )
    plan.add_argument(
        "--genre", default="pop", choices=sorted(GENRE_PROFILES), help="Musical genre."
    )
    plan.add_argument(
        "--mood", default="bright", choices=sorted(MOOD_PROGRESSIONS), help="Overall mood."
    )
    plan.add_argument(
        "--key", default="", help="Key root override (default: infer from the clip)."
    )
    plan.add_argument(
        "--mode", default="", help="Mode override, major/minor (default: infer)."
    )
    plan.add_argument(
        "--seed", type=int, default=0, help="Deterministic seed (default: %(default)s)."
    )
    plan.add_argument("--title", default="", help="Name for the generated track.")
    plan.add_argument(
        "--json", action="store_true", help="Emit the full plan as JSON."
    )
    plan.set_defaults(func=_cmd_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 on an invalid request)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
