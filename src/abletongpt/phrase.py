"""Build a longer phrase from an existing MIDI loop: tile it, optionally build up / add a fill.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_phrase_from_loop` repeats
a clip's notes ``repeats`` times back-to-back into one longer clip (turning a Session loop into an
arrangement-length phrase), and can optionally add a linear velocity **build-up** across the whole
phrase and a density **fill** on the final bar. Because tiling and the fill change the note count,
this is a *create* (a new clip), not an in-place edit -- the server tool writes it into an empty
slot via the non-overwriting ``create_midi_clip``.

Deterministic and read-only: the plan describes the new clip's notes; the separate create tool
writes them. It works on the user's own material (unlike ``create_part_variation``, which
regenerates a part from scratch with a different seed).
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_NOTES = 4096
_MAX_REPEATS = 64
_MAX_LENGTH = 4096.0
_MIN_FILL_DURATION = 0.125  # only subdivide notes at least this long for the fill


def _fingerprint(notes: list[dict[str, Any]], length: float) -> str:
    """Stable short hash of the source notes, for the review -> create guard."""
    canonical = ";".join(
        "%d,%.5f,%.5f,%d"
        % (
            int(note["pitch"]),
            float(note["start_time"]),
            float(note["duration"]),
            int(note.get("velocity", 100)),
        )
        for note in sorted(notes, key=lambda item: (float(item["start_time"]), int(item["pitch"])))
    )
    digest = hashlib.sha1(("%.5f|%s" % (length, canonical)).encode("utf-8"))
    return digest.hexdigest()[:16]


def _bar_beats(clip_data: dict[str, Any], loop_length: float) -> float:
    signature = clip_data.get("time_signature") or [4, 4]
    numerator = int(signature[0]) if signature else 4
    denominator = int(signature[1]) if len(signature) > 1 else 4
    bar = numerator * (4.0 / denominator)
    return min(bar, loop_length)


def build_phrase_from_loop(
    clip_data: dict[str, Any],
    repeats: int,
    build_up: float = 0.0,
    final_fill: bool = False,
) -> dict[str, Any]:
    """Return a read-only plan for a phrase built by tiling ``clip_data`` ``repeats`` times.

    ``build_up`` (0..1) ramps velocities from quieter at the start to full at the end across the
    whole phrase; ``final_fill`` adds a density fill (a subdivision of each note) on the last bar.
    Pitch/timing are preserved from the source; only the added fill notes and the build-up ramp are
    new. The note count grows with the tiling and the fill.
    """
    repeats = int(repeats)
    build_up = float(build_up)
    if not 1 <= repeats <= _MAX_REPEATS:
        raise ValueError("repeats must be between 1 and %d" % _MAX_REPEATS)
    if not 0.0 <= build_up <= 1.0:
        raise ValueError("build_up must be between 0 and 1")
    loop_length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < loop_length <= _MAX_LENGTH:
        raise ValueError("clip length must be between 0 and 4096 beats")
    source_notes = clip_data.get("notes", [])
    if not source_notes:
        raise ValueError("source MIDI clip contains no notes")

    total_length = loop_length * repeats
    if total_length > _MAX_LENGTH:
        raise ValueError("the phrase would exceed 4096 beats; use fewer repeats")

    # Tile the loop.
    tiled: list[dict[str, Any]] = []
    for repeat in range(repeats):
        offset = repeat * loop_length
        for note in source_notes:
            edited = dict(note)
            edited["start_time"] = round(float(note["start_time"]) + offset, 6)
            tiled.append(edited)

    # Density fill on the final bar: a subdivision copy of each note that starts there.
    added_fill_notes = 0
    if final_fill:
        fill_span = _bar_beats(clip_data, loop_length)
        fill_start = total_length - fill_span
        extra: list[dict[str, Any]] = []
        for note in tiled:
            start = float(note["start_time"])
            duration = float(note["duration"])
            if start < fill_start or duration < _MIN_FILL_DURATION:
                continue
            mid = start + duration / 2.0
            if mid >= total_length:
                continue
            extra.append(
                {
                    "pitch": int(note["pitch"]),
                    "start_time": round(mid, 6),
                    "duration": round(min(duration / 2.0, total_length - mid), 6),
                    "velocity": int(note.get("velocity", 100)),
                    "probability": float(note.get("probability", 1.0)),
                }
            )
        tiled.extend(extra)
        added_fill_notes = len(extra)

    if len(tiled) > _MAX_NOTES:
        raise ValueError("the phrase would exceed %d notes; use fewer repeats" % _MAX_NOTES)

    # Velocity build-up across the whole phrase: quiet -> full (floor keeps the start audible).
    if build_up:
        floor = 1.0 - 0.7 * build_up
        for note in tiled:
            position = float(note["start_time"]) / total_length  # 0..1
            multiplier = floor + (1.0 - floor) * position
            value = int(round(float(note.get("velocity", 100)) * multiplier))
            note["velocity"] = min(127, max(1, value))

    tiled.sort(key=lambda item: (float(item["start_time"]), int(item["pitch"])))

    return {
        "read_only": True,
        "repeats": repeats,
        "build_up": build_up,
        "final_fill": final_fill,
        "loop_length_beats": loop_length,
        "length_beats": round(total_length, 6),
        "source_note_count": len(source_notes),
        "note_count": len(tiled),
        "added_fill_notes": added_fill_notes,
        "source_fingerprint": _fingerprint(source_notes, loop_length),
        "notes": tiled,
    }
