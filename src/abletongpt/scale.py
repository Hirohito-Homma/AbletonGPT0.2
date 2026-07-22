"""Snap a MIDI clip's out-of-scale notes to the nearest note in a key/scale.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_scale_quantize_plan`
moves every note whose pitch class is not in the chosen scale to the nearest pitch that is,
leaving in-scale notes untouched. Snapping picks the closest scale pitch by absolute distance;
on a tie (a chromatic note exactly between two scale notes) it snaps **down**, and it never
leaves the 0..127 range (near the extremes it snaps inward). Timing/velocity/probability are
preserved and the note count never changes -- only pitch moves.

Deterministic and read-only: the server tool writes the result back through the same undoable
``apply_expression_to_clip`` path that expression editing and transposition use.
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_NOTES = 4096

# Semitone offsets from the tonic for each supported scale.
SCALE_INTERVALS: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),  # natural minor
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "melodic_minor": (0, 2, 3, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "major_pentatonic": (0, 2, 4, 7, 9),
    "minor_pentatonic": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
    "chromatic": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
}

# Alternative spellings that resolve to a canonical scale name.
_SCALE_ALIASES = {
    "ionian": "major",
    "aeolian": "minor",
    "natural_minor": "minor",
    "pentatonic": "major_pentatonic",
    "major_penta": "major_pentatonic",
    "minor_penta": "minor_pentatonic",
}


def parse_scale(name: str) -> str:
    """Normalize a scale name (case/space/hyphen-insensitive, with aliases). Raises on unknown."""
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    key = _SCALE_ALIASES.get(key, key)
    if key not in SCALE_INTERVALS:
        available = ", ".join(sorted(SCALE_INTERVALS))
        raise ValueError("unknown scale %r; available: %s" % (name, available))
    return key


def scale_pitch_classes(tonic_pc: int, scale_name: str) -> set[int]:
    """The set of allowed pitch classes for ``scale_name`` rooted at ``tonic_pc``."""
    intervals = SCALE_INTERVALS[parse_scale(scale_name)]
    return {(int(tonic_pc) + interval) % 12 for interval in intervals}


def snap_pitch(pitch: int, allowed_pcs: set[int]) -> int:
    """Nearest pitch to ``pitch`` whose pitch class is in ``allowed_pcs`` (tie -> down, in 0..127)."""
    if not allowed_pcs or pitch % 12 in allowed_pcs:
        return pitch
    for delta in range(1, 12):
        for candidate in (pitch - delta, pitch + delta):  # down first -> tie snaps down
            if 0 <= candidate <= 127 and candidate % 12 in allowed_pcs:
                return candidate
    return pitch


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


def build_scale_quantize_plan(
    clip_data: dict[str, Any],
    tonic_pc: int,
    scale_name: str,
) -> dict[str, Any]:
    """Return a read-only plan that snaps ``clip_data``'s out-of-scale notes into the scale.

    ``clip_data`` is a ``get_midi_clip_notes`` response. Each note keeps its timing/velocity/
    probability; only out-of-scale pitches move (to the nearest in-scale pitch). The note count
    never changes. ``changed_notes`` counts how many pitches were moved.
    """
    canonical_scale = parse_scale(scale_name)
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("clip length must be between 0 and 4096 beats")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)

    allowed = scale_pitch_classes(tonic_pc, canonical_scale)
    quantized: list[dict[str, Any]] = []
    changed_notes = 0
    for note in raw_notes:
        pitch = int(note["pitch"])
        snapped = snap_pitch(pitch, allowed)
        if snapped != pitch:
            changed_notes += 1
        edited = dict(note)
        edited["pitch"] = snapped
        quantized.append(edited)

    quantized.sort(key=lambda item: (float(item["start_time"]), item["pitch"]))

    return {
        "read_only": True,
        "tonic_pitch_class": int(tonic_pc) % 12,
        "scale": canonical_scale,
        "allowed_pitch_classes": sorted(allowed),
        "note_count": len(quantized),
        "changed_notes": changed_notes,
        "source_fingerprint": _fingerprint(raw_notes, length),
        "length_beats": length,
        "notes": quantized,
    }
