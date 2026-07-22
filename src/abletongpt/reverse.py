"""Reverse (retrograde) a MIDI clip in time.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_reverse_plan` mirrors every
note across the clip's timeline: a note that ends at time ``e`` starts at ``length - e`` after the
flip, so the whole pattern plays backwards. Pitch/velocity/probability, the note count and the clip
length are all preserved -- only the start times move (durations are kept, clamped to fit the clip).

Deterministic and read-only: the server tool writes the result back through the same undoable
``apply_expression_to_clip`` path the other in-place MIDI editors use.
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_NOTES = 4096
_MAX_LENGTH = 4096.0


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


def build_reverse_plan(clip_data: dict[str, Any]) -> dict[str, Any]:
    """Return a read-only plan that reverses ``clip_data`` in time (retrograde).

    ``clip_data`` is a ``get_midi_clip_notes`` response. Each note's new start is
    ``length - (start + duration)``; durations are preserved (clamped into the clip) and the note
    count and clip length are unchanged.
    """
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= _MAX_LENGTH:
        raise ValueError("clip length must be between 0 and 4096 beats")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)

    reversed_notes: list[dict[str, Any]] = []
    for note in raw_notes:
        start = float(note["start_time"])
        duration = float(note["duration"])
        new_start = length - (start + duration)
        # Notes whose tail runs past the clip end would flip to a negative start; pin to 0.
        new_start = min(max(new_start, 0.0), length)
        new_duration = min(duration, length - new_start)
        if new_duration <= 0.0:
            new_duration = duration  # degenerate (start at end); keep original, apply layer clamps
        edited = dict(note)
        edited["start_time"] = round(new_start, 6)
        edited["duration"] = round(new_duration, 6)
        reversed_notes.append(edited)

    reversed_notes.sort(key=lambda item: (item["start_time"], int(item["pitch"])))

    return {
        "read_only": True,
        "note_count": len(reversed_notes),
        "length_beats": length,
        "source_fingerprint": _fingerprint(raw_notes, length),
        "notes": reversed_notes,
    }
