#!/usr/bin/env python3
"""Example: insert an instrument or drum kit into a Live track.

Usage:
  PYTHONPATH=src python examples/live_insert_example.py --role bass --genre tech_house --mood dark --track-index 0
  PYTHONPATH=src python examples/live_insert_example.py --role drums --genre tech_house --mood dark --track-index 1
  PYTHONPATH=src python examples/live_insert_example.py --create-track --role chords --genre deep_house --mood warm

This script expects the Ableton Remote Script bridge to be running and connected.
"""

from __future__ import annotations

import argparse
import json

from abletongpt.server import (
    apply_live_drum_kit,
    apply_live_instrument_selection,
    create_track,
    get_track_devices,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Insert an instrument into a Live track.")
    parser.add_argument("--track-index", type=int, default=None, help="Live track index to modify.")
    parser.add_argument("--role", choices=["bass", "chords", "melody", "lead", "pad", "drums"], default="bass")
    parser.add_argument("--genre", default="tech_house")
    parser.add_argument("--mood", default="dark")
    parser.add_argument("--edition", default="unknown")
    parser.add_argument("--preferred-instrument", default="")
    parser.add_argument("--preferred-kit", default="")
    parser.add_argument("--create-track", action="store_true", help="Create a new MIDI track before inserting.")
    parser.add_argument("--track-name", default="AI Track")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.track_index is None:
        if args.create_track:
            created = create_track(track_type="midi", name=args.track_name, index=-1)
            args.track_index = int(created["index"])
            print(f"Created new MIDI track at index {args.track_index}")
        else:
            raise SystemExit("--track-index is required unless --create-track is used.")

    try:
        if args.role == "drums":
            result = apply_live_drum_kit(
                track_index=args.track_index,
                genre=args.genre,
                mood=args.mood,
                role="drums",
                preferred_kit=args.preferred_kit,
            )
        else:
            result = apply_live_instrument_selection(
                track_index=args.track_index,
                role=args.role,
                genre=args.genre,
                mood=args.mood,
                live_edition=args.edition,
                preferred_instrument=args.preferred_instrument,
            )
    except RuntimeError as exc:
        if "not a MIDI track" not in str(exc):
            raise
        created = create_track(track_type="midi", name=args.track_name, index=-1)
        args.track_index = int(created["index"])
        print(f"Selected track was not MIDI; created a new MIDI track at index {args.track_index}")
        if args.role == "drums":
            result = apply_live_drum_kit(
                track_index=args.track_index,
                genre=args.genre,
                mood=args.mood,
                role="drums",
                preferred_kit=args.preferred_kit,
            )
        else:
            result = apply_live_instrument_selection(
                track_index=args.track_index,
                role=args.role,
                genre=args.genre,
                mood=args.mood,
                live_edition=args.edition,
                preferred_instrument=args.preferred_instrument,
            )

    devices = get_track_devices(args.track_index)

    print(json.dumps({
        "track_index": args.track_index,
        "role": args.role,
        "genre": args.genre,
        "mood": args.mood,
        "insert_result": result,
        "devices": devices.get("devices", []),
        "device_count": len(devices.get("devices", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
