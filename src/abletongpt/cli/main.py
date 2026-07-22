"""Unified command-line entry point that dispatches to the per-engine CLIs.

    abletongpt-cli compose --title Demo --genre pop --mood bright --key C --tempo 120
    abletongpt-cli contextual analyze --clip clip.json
    abletongpt-cli loudness track.wav --json
    abletongpt-cli --help            # list every subcommand

Each subcommand delegates verbatim to ``abletongpt.cli.<name>.main`` -- this module adds
no behaviour of its own. ``abletongpt-cli compose --help`` therefore shows the compose
CLI's own help, and options/positional arguments are passed straight through untouched.
Pure dispatch: it reads no files, opens no sockets and never touches Ableton.
"""

from __future__ import annotations

import argparse
from typing import Callable, Dict, Tuple

from . import arrange, compose, contextual, expression, instruments, jobs, loudness, vocal

#: Callable that runs a subcommand with the remaining argv and returns an exit code.
_Handler = Callable[[list], int]

#: Ordered map of subcommand name -> (delegate ``main``, one-line help).
_SUBCOMMANDS: Dict[str, Tuple[_Handler, str]] = {
    "compose": (compose.main, "Generate a deterministic multi-track song sketch."),
    "contextual": (
        contextual.main,
        "Analyze an existing MIDI clip or plan a complementary part.",
    ),
    "instruments": (
        instruments.main,
        "Select native instruments for a role / genre / mood.",
    ),
    "expression": (
        expression.main,
        "Add expressive performance (accent / swing / humanize) to a MIDI clip.",
    ),
    "vocal": (vocal.main, "Plan an editable AI vocal guide from lyrics."),
    "arrange": (arrange.main, "Build or validate an Arrangement-View section plan."),
    "loudness": (
        loudness.main,
        "Analyze WAV/AIFF loudness (LUFS / LRA / peak) offline.",
    ),
    "jobs": (jobs.main, "Create, run and inspect multi-step job plans."),
}


def build_parser() -> argparse.ArgumentParser:
    """Top-level parser whose only job is to pick a subcommand and pass the rest on."""
    parser = argparse.ArgumentParser(
        prog="abletongpt-cli",
        description="Unified entry point for the AbletonGPT engine CLIs.",
        epilog="Run 'abletongpt-cli <command> --help' for command-specific options.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for name, (_handler, help_text) in _SUBCOMMANDS.items():
        # ``add_help=False`` so a trailing ``-h`` reaches the delegate's own parser.
        sub.add_parser(name, help=help_text, add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch ``argv`` to the selected subcommand's ``main``."""
    parser = build_parser()
    args, rest = parser.parse_known_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    handler, _help = _SUBCOMMANDS[args.command]
    return handler(rest)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
