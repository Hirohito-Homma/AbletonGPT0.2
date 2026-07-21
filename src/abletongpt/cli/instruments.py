"""Command-line entry point for planning native-instrument selections.

    python -m abletongpt.cli.instruments --genre edm --mood uplifting
    python -m abletongpt.cli.instruments --genre lofi --mood chill --roles keys bass drums
    python -m abletongpt.cli.instruments --genre pop --mood bright --edition standard --json

Pure planning only: this reads no files and never touches Ableton. It just runs the
deterministic :func:`abletongpt.instruments.build_instrument_plan` engine and prints the
result -- as a human summary, or as machine-readable JSON with ``--json``. Actually
inserting an instrument is a separate, confirmation-gated step in Live.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..instruments import (
    GENRE_PROFILES,
    LIVE_EDITIONS,
    MOOD_PROGRESSIONS,
    SUPPORTED_ROLES,
    build_instrument_plan,
)


def _print_plan(plan: dict, *, as_json: bool) -> None:
    """Print an instrument plan as JSON or a human-readable summary."""
    if as_json:
        # ensure_ascii=False keeps the Japanese role names/reasons readable; still valid JSON.
        print(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "genre: %s  mood: %s  edition: %s"
        % (plan["genre"], plan["mood"], plan["live_edition"])
    )
    for selection in plan["selections"]:
        print(
            "  %-8s %-8s -> %-12s [%s]"
            % (
                selection["role"],
                selection["role_name_ja"],
                selection["selected_instrument"],
                ", ".join(selection["candidates"]),
            )
        )


def _cmd_plan(args: argparse.Namespace) -> int:
    try:
        plan = build_instrument_plan(
            genre=args.genre,
            mood=args.mood,
            roles=args.roles,
            live_edition=args.edition,
        )
    except ValueError as exc:
        # argparse choices already reject bad single values; this guards the remaining
        # engine rules (e.g. too many roles) with a clean message instead of a traceback.
        print("instruments: %s" % exc, file=sys.stderr)
        return 2
    _print_plan(plan, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.instruments",
        description="Plan deterministic native-instrument selections (no Ableton needed).",
    )
    parser.add_argument(
        "--genre", required=True, choices=sorted(GENRE_PROFILES), help="Musical genre."
    )
    parser.add_argument(
        "--mood", required=True, choices=sorted(MOOD_PROGRESSIONS), help="Overall mood."
    )
    parser.add_argument(
        "--roles",
        nargs="+",
        choices=sorted(SUPPORTED_ROLES),
        default=None,
        metavar="ROLE",
        help="Instrument roles to plan (default: chords bass melody drums).",
    )
    parser.add_argument(
        "--edition",
        default="unknown",
        choices=sorted(LIVE_EDITIONS),
        help="Live edition to prefer (default: %(default)s).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full plan as machine-readable JSON on stdout.",
    )
    parser.set_defaults(func=_cmd_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 on an invalid plan request)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
