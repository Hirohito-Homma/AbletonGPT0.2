"""Edit MIDI note lengths: legato (join/gate) and split (subdivide).

Pure logic, stdlib only -- no Live connection and no NumPy. Two in-place operations on a clip's
notes (the clip length never changes):

* :func:`build_legato_plan` sets each note's duration from the gap to the next note **of the same
  pitch** (or the clip end for the last one), scaled by ``gate``: ``gate=1.0`` fully connects the
  notes (legato / merge the gaps), ``gate<1`` leaves a proportional gap (more staccato). The note
  count is unchanged.
* :func:`build_split_plan` divides each note into ``divisions`` equal shorter notes of the same
  pitch/velocity (subdivision). The note count grows by that factor.

Both preserve pitch/velocity/probability. Deterministic and read-only: the server tools write the
result back through the same undoable ``apply_expression_to_clip`` path the other MIDI editors use
(it clears and re-adds the clip's notes, so a changed note count is fine).
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_NOTES = 4096
_MAX_LENGTH = 4096.0
_MIN_DURATION = 1e-4


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


def _validate_clip(clip_data: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= _MAX_LENGTH:
        raise ValueError("clip length must be between 0 and 4096 beats")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)
    return length, raw_notes


def build_legato_plan(clip_data: dict[str, Any], gate: float = 1.0) -> dict[str, Any]:
    """Return a read-only plan that legatoes ``clip_data`` -- extend notes toward the next same pitch.

    ``gate`` (0<gate<=1) scales the gap to the next same-pitch note: 1.0 fully connects (legato),
    smaller values leave a proportional gap (staccato). Only durations change; the note count is
    unchanged.
    """
    gate = float(gate)
    if not 0.0 < gate <= 1.0:
        raise ValueError("gate must be greater than 0 and no more than 1")
    length, raw_notes = _validate_clip(clip_data)

    # Next-onset per pitch: sort each pitch's note start times.
    starts_by_pitch: dict[int, list[float]] = {}
    for note in raw_notes:
        starts_by_pitch.setdefault(int(note["pitch"]), []).append(float(note["start_time"]))
    for pitch in starts_by_pitch:
        starts_by_pitch[pitch].sort()

    changed_notes = 0
    edited_notes: list[dict[str, Any]] = []
    for note in raw_notes:
        pitch = int(note["pitch"])
        start = float(note["start_time"])
        # The next distinct onset of this pitch, else the clip end.
        next_onset = length
        for onset in starts_by_pitch[pitch]:
            if onset > start + _MIN_DURATION:
                next_onset = onset
                break
        gap = next_onset - start
        new_duration = round(max(_MIN_DURATION, min(gap * gate, length - start)), 6)
        if abs(new_duration - float(note["duration"])) > 1e-6:
            changed_notes += 1
        edited = dict(note)
        edited["duration"] = new_duration
        edited_notes.append(edited)

    edited_notes.sort(key=lambda item: (float(item["start_time"]), int(item["pitch"])))
    return {
        "read_only": True,
        "operation": "legato",
        "gate": gate,
        "note_count": len(edited_notes),
        "changed_notes": changed_notes,
        "length_beats": length,
        "source_fingerprint": _fingerprint(raw_notes, length),
        "notes": edited_notes,
    }


def build_split_plan(clip_data: dict[str, Any], divisions: int) -> dict[str, Any]:
    """Return a read-only plan that splits every note in ``clip_data`` into ``divisions`` parts.

    Each part keeps the pitch/velocity/probability and takes an equal share of the original
    duration. The note count is multiplied by ``divisions``.
    """
    divisions = int(divisions)
    if not 2 <= divisions <= 16:
        raise ValueError("divisions must be between 2 and 16")
    length, raw_notes = _validate_clip(clip_data)
    if len(raw_notes) * divisions > _MAX_NOTES:
        raise ValueError("splitting would exceed %d notes; use fewer divisions" % _MAX_NOTES)

    split_notes: list[dict[str, Any]] = []
    for note in raw_notes:
        start = float(note["start_time"])
        part = float(note["duration"]) / divisions
        for index in range(divisions):
            piece = dict(note)
            piece["start_time"] = round(start + index * part, 6)
            piece["duration"] = round(part, 6)
            split_notes.append(piece)

    split_notes.sort(key=lambda item: (float(item["start_time"]), int(item["pitch"])))
    return {
        "read_only": True,
        "operation": "split",
        "divisions": divisions,
        "source_note_count": len(raw_notes),
        "note_count": len(split_notes),
        "length_beats": length,
        "source_fingerprint": _fingerprint(raw_notes, length),
        "notes": split_notes,
    }
