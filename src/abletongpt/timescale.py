"""Half-time / double-time a MIDI clip by scaling note timing.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_timescale_plan` multiplies
every note's start and duration by a factor and scales the clip length to match: ``factor=2.0`` is
**half-time** (the pattern plays half as fast over twice the length) and ``factor=0.5`` is
**double-time** (twice as fast over half the length). Pitch/velocity/probability and the note count
are preserved -- only timing and the clip length change.

Because the clip length changes, this is a *create* (a new clip), not an in-place edit: the server
tool writes it into an empty slot via the non-overwriting ``create_midi_clip``. :func:`factor_for`
maps the named modes ``"half"``/``"double"`` to their factors.
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_NOTES = 4096
_MAX_LENGTH = 4096.0
_NAMED_FACTORS = {"half": 2.0, "half-time": 2.0, "double": 0.5, "double-time": 0.5}


def factor_for(mode: str) -> float:
    """Map a named mode (``"half"``/``"double"``) to a time-scale factor. Raises on unknown."""
    key = mode.strip().lower().replace("_", "-")
    if key not in _NAMED_FACTORS:
        raise ValueError("mode must be 'half' or 'double' (got %r)" % mode)
    return _NAMED_FACTORS[key]


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


def build_timescale_plan(clip_data: dict[str, Any], factor: float) -> dict[str, Any]:
    """Return a read-only plan that scales ``clip_data``'s note timing (and length) by ``factor``.

    ``factor`` > 0: 2.0 = half-time (slower/longer), 0.5 = double-time (faster/shorter). Pitch,
    velocity, probability and the note count are preserved; only start/duration and the clip length
    scale. The new length must stay within 0..4096 beats.
    """
    factor = float(factor)
    if not 0.0 < factor <= 64.0:
        raise ValueError("factor must be greater than 0 and no more than 64")
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= _MAX_LENGTH:
        raise ValueError("clip length must be between 0 and 4096 beats")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)

    new_length = length * factor
    if new_length > _MAX_LENGTH:
        raise ValueError("the scaled clip would exceed 4096 beats; use a smaller factor")

    scaled: list[dict[str, Any]] = []
    for note in raw_notes:
        edited = dict(note)
        edited["start_time"] = round(float(note["start_time"]) * factor, 6)
        edited["duration"] = round(float(note["duration"]) * factor, 6)
        scaled.append(edited)

    scaled.sort(key=lambda item: (float(item["start_time"]), int(item["pitch"])))

    return {
        "read_only": True,
        "factor": factor,
        "note_count": len(scaled),
        "source_length_beats": length,
        "length_beats": round(new_length, 6),
        "source_fingerprint": _fingerprint(raw_notes, length),
        "notes": scaled,
    }
