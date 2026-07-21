"""Command-line entry points for producing and checking arrangement plans.

    python -m abletongpt.cli.arrange template      --name demo --out arr.json
    python -m abletongpt.cli.arrange create-simple --name demo --out arr.json
    python -m abletongpt.cli.arrange validate       --arrangement arr.json

The output JSON is exactly what ``python -m abletongpt.cli.jobs create`` consumes, so
this closes the loop: a user can go from nothing to a runnable job plan without hand
-writing any JSON. All logic here is pure (no Ableton, no socket).
"""

from __future__ import annotations

import argparse
import json
import sys

from ..arrange.models import ArrangementPlan
from ..arrange.presets import simple_arrangement
from .serialization import (
    arrangement_from_dict,
    arrangement_to_dict,
    read_json_document,
    write_json_document,
)


# --- validation ------------------------------------------------------------------

def _validation_errors(plan: ArrangementPlan) -> list[str]:
    """Return human-readable problems with ``plan`` (empty list = valid)."""
    errors: list[str] = []
    if not plan.sections:
        errors.append("arrangement has no sections")

    seen: set[str] = set()
    for section in plan.sections:
        if section.section_id in seen:
            errors.append("duplicate section_id: %r" % section.section_id)
        seen.add(section.section_id)
        if section.start_bar <= 0:
            errors.append(
                "section %r: start_bar must be positive (got %d)"
                % (section.section_id, section.start_bar)
            )
        if section.length_bars <= 0:
            errors.append(
                "section %r: length_bars must be positive (got %d)"
                % (section.section_id, section.length_bars)
            )
    return errors


# --- subcommands -----------------------------------------------------------------

def _cmd_template(args: argparse.Namespace) -> int:
    # The template is just the simple layout under the user's chosen name -- a valid,
    # ready-to-edit starting point rather than a set of placeholders to fill in.
    plan = simple_arrangement(args.name)
    out_path = write_json_document(arrangement_to_dict(plan), args.out)
    print(
        "wrote arrangement template '%s' with %d section(s) -> %s"
        % (plan.name, len(plan.sections), out_path)
    )
    return 0


def _cmd_create_simple(args: argparse.Namespace) -> int:
    plan = simple_arrangement(args.name)
    out_path = write_json_document(arrangement_to_dict(plan), args.out)
    print(
        "wrote arrangement '%s' with %d section(s) -> %s"
        % (plan.name, len(plan.sections), out_path)
    )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    as_json = args.json
    try:
        document = read_json_document(args.arrangement)
        plan = arrangement_from_dict(document)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # The document could not even be read/reconstructed -- there is no plan to
        # summarize, so name/counts are null and the exception is the sole error.
        if as_json:
            print(
                json.dumps(
                    {
                        "valid": False,
                        "name": None,
                        "section_count": None,
                        "total_bars": None,
                        "errors": [str(exc)],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print("invalid arrangement: %s" % exc, file=sys.stderr)
        return 1

    errors = _validation_errors(plan)
    if as_json:
        # Machine-readable result on stdout; errors travel inside the payload rather than
        # on stderr, but the exit code still signals validity (0 ok, 1 invalid).
        print(
            json.dumps(
                {
                    "valid": not errors,
                    "name": plan.name,
                    "section_count": len(plan.sections),
                    "total_bars": plan.total_bars,
                    "errors": errors,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if errors else 0

    if errors:
        for error in errors:
            print("invalid arrangement: %s" % error, file=sys.stderr)
        return 1

    print(
        "ok: %d section(s), total %d bar(s)" % (len(plan.sections), plan.total_bars)
    )
    return 0


# --- argument parsing ------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.arrange",
        description="Create, template, and validate AbletonGPT arrangement plans.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    template = sub.add_parser(
        "template", help="Write an editable arrangement plan JSON to start from."
    )
    template.add_argument("--name", required=True, help="Name for the arrangement.")
    template.add_argument("--out", required=True, help="Path to write the JSON.")
    template.set_defaults(func=_cmd_template)

    simple = sub.add_parser(
        "create-simple",
        help="Write a ready-to-use default arrangement plan JSON.",
    )
    simple.add_argument("--name", required=True, help="Name for the arrangement.")
    simple.add_argument("--out", required=True, help="Path to write the JSON.")
    simple.set_defaults(func=_cmd_create_simple)

    validate = sub.add_parser(
        "validate", help="Check an arrangement plan JSON and report problems."
    )
    validate.add_argument(
        "--arrangement", required=True, help="Path to an arrangement plan JSON file."
    )
    validate.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON result (valid flag, counts, errors) on stdout.",
    )
    validate.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 1 on invalid arrangement)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
