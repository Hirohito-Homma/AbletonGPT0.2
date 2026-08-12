"""Command-line entry point for turning natural-language prompts into SongSpec drafts."""

from __future__ import annotations

import argparse
import json

from ..songspec import build_song_spec_from_prompt, song_spec_to_dict, song_spec_to_yaml


def _print_spec(spec, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(song_spec_to_dict(spec), indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(song_spec_to_yaml(spec))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.intent",
        description="Turn a natural-language music request into a first-pass SongSpec draft.",
    )
    parser.add_argument("prompt", help="Natural-language music request.")
    parser.add_argument(
        "--title",
        default=None,
        help="Optional title override; otherwise a short title is inferred from the prompt.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the SongSpec draft as JSON instead of YAML.",
    )
    parser.set_defaults(func=_cmd_intent)
    return parser


def _cmd_intent(args: argparse.Namespace) -> int:
    spec = build_song_spec_from_prompt(args.prompt, title=args.title)
    _print_spec(spec, as_json=args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())