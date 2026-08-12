"""One-shot Live flow: create or reuse MIDI tracks, insert instruments, verify readback."""

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


def _parse_into(values: list[str]) -> dict[str, int]:
    """Parse ``role:index`` pairs naming existing tracks to use instead of new ones.

    An index is a fact about the Set as it is right now, so it is taken verbatim
    and never guessed: an unparseable pair is refused rather than skipped, which
    would quietly create a track the caller did not want.
    """

    mapping: dict[str, int] = {}
    for value in values:
        role, separator, raw = value.partition(":")
        role = role.strip().lower()
        if not separator or not role:
            raise ValueError(f"--into expects role:index, got {value!r}")
        try:
            index = int(raw)
        except ValueError:
            raise ValueError(f"--into track index must be an integer, got {raw!r}") from None
        if index < 0:
            raise ValueError(f"--into track index must not be negative, got {index}")
        if role in mapping:
            raise ValueError(f"--into names role {role!r} twice")
        mapping[role] = index
    return mapping


def _run_flow(
    roles: list[str],
    *,
    genre: str = "tech_house",
    mood: str = "dark",
    into: dict[str, int] | None = None,
) -> dict[str, Any]:
    into = into or {}
    unknown = sorted(set(into) - set(roles))
    if unknown:
        # Silently ignoring these would create a new track for the role the
        # caller thought they had pointed somewhere.
        raise ValueError("--into names roles that are not being run: " + ", ".join(unknown))
    results: list[dict[str, Any]] = []
    for role in roles:
        name = TRACK_NAMES.get(role, role.title())
        existing = into.get(role)
        if existing is None:
            created = create_track(track_type="midi", name=name, index=-1)
            track_index = int(created["index"])
        else:
            track_index = existing
        try:
            inserted = _insert_for_role(track_index, role, genre, mood)
            readback = get_track_devices(track_index)
            devices = readback.get("devices", [])
            ok = bool(devices)
            results.append({
                "track_index": track_index,
                "role": role,
                "name": name,
                "created_track": existing is None,
                "inserted": inserted,
                "devices": devices,
                "ok": ok,
            })
        except Exception as exc:  # pragma: no cover - real Live runtime branch
            results.append({
                "track_index": track_index,
                "role": role,
                "name": name,
                "created_track": existing is None,
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


def _device_names(item: dict[str, Any]) -> list[str]:
    """Return just the device names from one result entry, in chain order."""
    names: list[str] = []
    for device in item.get("devices") or []:
        if isinstance(device, dict):
            names.append(str(device.get("name", "?")))
        else:
            names.append(str(device))
    return names


def _print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"genre={result['genre']} mood={result['mood']}")
    for item in result["results"]:
        status = "OK" if item.get("ok") else "FAIL"
        # Only the device *names*: get_track_devices returns every parameter of every
        # device, which is ~40 KB per track against a real Live and buries the status.
        names = ", ".join(_device_names(item)) or "none"
        # Whether the track was created or reused decides what undoing this means.
        origin = "new" if item.get("created_track", True) else "existing"
        print(
            f"  [{status}] track={item['track_index']} ({origin}) "
            f"role={item['role']} devices={names}"
        )
        error = item.get("error")
        if error:
            print(f"         {error}")


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
    parser.add_argument(
        "--into",
        action="append",
        default=[],
        metavar="ROLE:INDEX",
        help=(
            "Insert into an existing track instead of creating one, as role:index "
            "(repeatable, e.g. --into bass:3). Roles left out still get a new track. "
            "Live refuses a track that already has an instrument, so the target must "
            "be empty; check indices with get_live_state."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    parser.set_defaults(func=_cmd_run)
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        roles = _parse_roles(args.roles)
        into = _parse_into(args.into)
        result = _run_flow(roles, genre=args.genre, mood=args.mood, into=into)
    except ValueError as exc:
        print(f"live-flow: {exc}", file=sys.stderr)
        return 2
    _print_result(result, as_json=args.json)
    return 0 if result["all_ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
