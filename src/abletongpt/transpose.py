"""Transpose a MIDI clip's notes by a fixed interval (a chromatic key change).

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_transpose_plan` shifts
every note's pitch by a constant number of semitones. A constant chromatic shift preserves every
interval, so it is a true key change (unlike a diatonic, in-scale transpose). Any note that would
leave the 0..127 MIDI range is folded back in by whole octaves, which keeps its pitch class and
keeps the note count unchanged. Deterministic and read-only: the server tool writes the result
back through the same undoable ``apply_expression_to_clip`` path that expression editing uses.

:func:`shift_to_target_pc` computes the semitone shift that moves a source tonic pitch class to a
target one (nearest direction by default), so the server tool can turn a "transpose to G major"
request into a concrete offset.
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_NOTES = 4096
_MAX_SHIFT = 48  # four octaves either way -- generous but bounded


def shift_to_target_pc(source_pc: int, target_pc: int, direction: str = "nearest") -> int:
    """Semitones to move ``source_pc`` to ``target_pc`` (pitch classes 0..11).

    ``direction`` picks which way when the two are apart: ``"nearest"`` (default, in -5..+6),
    ``"up"`` (0..+11) or ``"down"`` (-11..0).
    """
    up = (int(target_pc) - int(source_pc)) % 12  # 0..11, shortest upward move
    if direction == "up":
        return up
    if direction == "down":
        return up - 12 if up else 0
    if direction == "nearest":
        return up if up <= 6 else up - 12
    raise ValueError("direction must be 'nearest', 'up', or 'down'")


def _fold_into_range(pitch: int) -> tuple[int, bool]:
    """Fold a pitch back into 0..127 by whole octaves, preserving its pitch class."""
    folded = False
    while pitch < 0:
        pitch += 12
        folded = True
    while pitch > 127:
        pitch -= 12
        folded = True
    return pitch, folded


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


def build_transpose_plan(clip_data: dict[str, Any], semitones: int) -> dict[str, Any]:
    """Return a read-only plan that shifts every note in ``clip_data`` by ``semitones``.

    ``clip_data`` is a ``get_midi_clip_notes`` response (``{length_beats, notes: [...]}``). The
    plan keeps each note's timing/velocity/probability and only changes pitch; notes pushed out
    of range are octave-folded (reported as ``folded_notes``). The note count never changes.
    """
    semitones = int(semitones)
    if not -_MAX_SHIFT <= semitones <= _MAX_SHIFT:
        raise ValueError("semitones must be between -%d and %d" % (_MAX_SHIFT, _MAX_SHIFT))
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("clip length must be between 0 and 4096 beats")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)

    source_pitches: list[int] = []
    transposed: list[dict[str, Any]] = []
    folded_notes = 0
    for note in raw_notes:
        pitch = int(note["pitch"])
        source_pitches.append(pitch)
        new_pitch, folded = _fold_into_range(pitch + semitones)
        if folded:
            folded_notes += 1
        edited = dict(note)
        edited["pitch"] = new_pitch
        transposed.append(edited)

    transposed.sort(key=lambda item: (float(item["start_time"]), item["pitch"]))
    result_pitches = [note["pitch"] for note in transposed]

    return {
        "read_only": True,
        "semitones": semitones,
        "note_count": len(transposed),
        "folded_notes": folded_notes,
        "source_pitch_range": {"lowest": min(source_pitches), "highest": max(source_pitches)},
        "result_pitch_range": {"lowest": min(result_pitches), "highest": max(result_pitches)},
        "source_fingerprint": _fingerprint(raw_notes, length),
        "length_beats": length,
        "notes": transposed,
    }
