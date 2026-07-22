"""Quantize a MIDI clip's note timing to a grid, with strength and optional swing.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_quantize_plan` snaps
each note's start time toward the nearest grid line. ``strength`` (0..1) sets how far each note
moves toward its grid target (1 = full snap, 0 = no move), matching Live's quantize Amount.
``swing`` (0..1) pushes the off-grid subdivisions (odd grid positions -- the "and"s) later by up
to half a grid step, for a swung feel (~0.6 approximates a triplet swing). Only ``start_time``
moves; pitch/duration/velocity/probability are preserved and the note count never changes. Notes
never snap to the grid line at the clip end -- the last grid line before the end is used instead,
so a quantized start always stays inside the clip.

Deterministic and read-only: the server tool writes the result back through the same undoable
``apply_expression_to_clip`` path the other MIDI editors use.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

_MAX_NOTES = 4096
_EPSILON = 1e-9


def _fingerprint(notes: list[dict[str, Any]], length: float) -> str:
    """Stable short hash of the source notes, for the review -> apply guard."""
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


def build_quantize_plan(
    clip_data: dict[str, Any],
    grid_beats: float = 0.25,
    strength: float = 1.0,
    swing: float = 0.0,
) -> dict[str, Any]:
    """Return a read-only plan that quantizes ``clip_data``'s note starts to ``grid_beats``.

    ``clip_data`` is a ``get_midi_clip_notes`` response. ``strength`` and ``swing`` are each in
    0..1. Only ``start_time`` changes; timing shifts are reported (``moved_notes``,
    ``max_abs_shift_beats``, ``average_abs_shift_beats``) and the note count is unchanged.
    """
    grid_beats = float(grid_beats)
    strength = float(strength)
    swing = float(swing)
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("clip length must be between 0 and 4096 beats")
    if not 0.0 < grid_beats <= length:
        raise ValueError("grid_beats must be greater than 0 and no larger than the clip length")
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be between 0 and 1")
    if not 0.0 <= swing <= 1.0:
        raise ValueError("swing must be between 0 and 1")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)

    # Largest grid index whose line still falls strictly inside the clip.
    max_index = max(0, int(math.ceil((length - _EPSILON) / grid_beats)) - 1)
    swing_offset = swing * (grid_beats / 2.0)

    quantized: list[dict[str, Any]] = []
    shifts: list[float] = []
    moved_notes = 0
    for note in raw_notes:
        start = float(note["start_time"])
        index = int(math.floor(start / grid_beats + 0.5))
        index = min(max(index, 0), max_index)
        target = index * grid_beats + (swing_offset if index % 2 else 0.0)
        new_start = start + strength * (target - start)
        # Keep the start inside the clip (never at/after the end).
        new_start = min(max(new_start, 0.0), length - _EPSILON)
        new_start = round(new_start, 6)
        shift = new_start - start
        if abs(shift) > 1e-6:
            moved_notes += 1
        shifts.append(abs(shift))
        edited = dict(note)
        edited["start_time"] = new_start
        quantized.append(edited)

    quantized.sort(key=lambda item: (item["start_time"], int(item["pitch"])))

    return {
        "read_only": True,
        "grid_beats": grid_beats,
        "strength": strength,
        "swing": swing,
        "note_count": len(quantized),
        "moved_notes": moved_notes,
        "max_abs_shift_beats": round(max(shifts), 6) if shifts else 0.0,
        "average_abs_shift_beats": round(sum(shifts) / len(shifts), 6) if shifts else 0.0,
        "source_fingerprint": _fingerprint(raw_notes, length),
        "length_beats": length,
        "notes": quantized,
    }
