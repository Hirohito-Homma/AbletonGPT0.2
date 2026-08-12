"""One-shot Live flow: create MIDI tracks, insert instruments, and verify readback."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ..server import (
    apply_live_drum_kit,
    apply_live_instrument_selection,
    create_track,
    get_track_devices,
)

DEFAULT_ROLES = ["bass", "chords", "melody", "drums"]
TRACK_NAMES = {
    "bass": "Bass",
    "chords": "Chords",
    "melody": "Melody",
    "lead": "Lead",
    "pad": "Pad",
    "drums": "Drums",
}


def _parse_roles(raw: str) -> list[str]:
    roles = [role.strip().lower() for role in raw.split(",") if role.strip()]
    if not roles:
        raise ValueError("--roles cannot be empty")
    return roles


def _insert_for_role(track_index: int, role: str, genre: str, mood: str) -> dict[str, Any]:
    if role == "drums":
        return apply_live_drum_kit(
            track_index=track_index,
            genre=genre,
            mood=mood,
            role="drums",
            preferred_kit="",
        )
    return apply_live_instrument_selection(
        track_index=track_index,
        role=role,
        genre=genre,
        mood=mood,
        live_edition="unknown",
        preferred_instrument="",
    )


def _run_flow(roles: list[str], *, genre: str = "tech_house", mood: str = "dark") -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for role in roles:
        name = TRACK_NAMES.get(role, role.title())
        created = create_track(track_type="midi", name=name, index=-1)
        track_index = int(created["index"])
        try:
            inserted = _insert_for_role(track_index, role, genre, mood)
            readback = get_track_devices(track_index)
            devices = readback.get("devices", [])
            ok = bool(devices)
            results.append({
                "track_index": track_index,
                "role": role,
                "name": name,
                "inserted": inserted,
                "devices": devices,
                "ok": ok,
            })
        except Exception as exc:  # pragma: no cover - real Live runtime branch
            results.append({
                "track_index": track_index,
                "role": role,
                "name": name,
                "ok": False,
                "error": str(exc),
            })
    return {
        "genre": genre,
        "mood": mood,
        "roles": roles,
        "all_ok": all(bool(item.get("ok")) for item in results),
        "results": results,
    }


def _print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"genre={result['genre']} mood={result['mood']}")
    for item in result["results"]:
        status = "OK" if item.get("ok") else "FAIL"
        devices = item.get("devices") or []
        print(f"  [{status}] track={item['track_index']} role={item['role']} devices={devices}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.live_flow",
        description="Create MIDI tracks and insert native instruments in one real Live flow.",
    )
    parser.add_argument("--genre", default="tech_house", help="Genre to use for instrument selection.")
    parser.add_argument("--mood", default="dark", help="Mood to use for instrument selection.")
    parser.add_argument(
        "--roles",
        default=",".join(DEFAULT_ROLES),
        help="Comma-separated roles to create and populate (default: %(default)s).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    parser.set_defaults(func=_cmd_run)
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        roles = _parse_roles(args.roles)
    except ValueError as exc:
        print(f"live-flow: {exc}", file=sys.stderr)
        return 2
    result = _run_flow(roles, genre=args.genre, mood=args.mood)
    _print_result(result, as_json=args.json)
    return 0 if result["all_ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
