"""Transcribe a MIDI clip (chord progression) from one key/scale to another by scale degree.

Pure logic, stdlib only -- no Live connection and no NumPy. Unlike :mod:`abletongpt.transpose`
(a constant chromatic shift, blind to mode) this is a *diatonic / modal* remap: each note is
resolved to its scale degree in the source key (plus its octave and any chromatic offset from
that degree), then rebuilt on the same degree of the target key/scale. That preserves harmonic
function, so a I-IV-V in C major becomes i-iv-v in C minor (the thirds/sixths/sevenths move with
the mode) rather than a literal transposition.

Because the mapping is degree-for-degree, the source and target scales must have the **same
number of degrees** (both 7-note diatonic, or both pentatonic, ...). When the scales are the same
shape the remap reduces to a plain diatonic transposition. Notes pushed out of 0..127 are
octave-folded; timing/velocity/probability are preserved and the note count never changes.

Deterministic and read-only: the server tool writes the result back through the same undoable
``apply_expression_to_clip`` path the other MIDI editors use.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .scale import SCALE_INTERVALS, parse_scale

_MAX_NOTES = 4096


def _degree_and_delta(within: int, intervals: tuple[int, ...]) -> tuple[int, int]:
    """Nearest scale-degree index to a 0..11 offset, plus the chromatic delta (tie -> lower degree)."""
    best = min(range(len(intervals)), key=lambda index: (abs(within - intervals[index]), intervals[index]))
    return best, within - intervals[best]


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


def _remap_pitch(
    pitch: int,
    source_tonic: int,
    source_intervals: tuple[int, ...],
    target_tonic: int,
    target_intervals: tuple[int, ...],
) -> tuple[int, bool]:
    rel = pitch - source_tonic
    octave, within = divmod(rel, 12)  # within in 0..11, octave floors toward -inf
    degree, delta = _degree_and_delta(within, source_intervals)
    new_pitch = target_tonic + 12 * octave + target_intervals[degree] + delta
    return _fold_into_range(new_pitch)


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


def build_scale_remap_plan(
    clip_data: dict[str, Any],
    source_tonic: int,
    source_scale: str,
    target_tonic: int,
    target_scale: str,
) -> dict[str, Any]:
    """Return a read-only plan that remaps ``clip_data`` from one key/scale to another by degree.

    ``clip_data`` is a ``get_midi_clip_notes`` response. The source and target scales must have
    the same number of degrees. Each note keeps its timing/velocity/probability; only pitch moves.
    """
    source_name = parse_scale(source_scale)
    target_name = parse_scale(target_scale)
    source_intervals = SCALE_INTERVALS[source_name]
    target_intervals = SCALE_INTERVALS[target_name]
    if len(source_intervals) != len(target_intervals):
        raise ValueError(
            "source scale %r (%d degrees) and target scale %r (%d degrees) must have the same "
            "number of degrees for a diatonic remap"
            % (source_name, len(source_intervals), target_name, len(target_intervals))
        )

    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("clip length must be between 0 and 4096 beats")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)

    source_tonic %= 12
    target_tonic %= 12
    remapped: list[dict[str, Any]] = []
    changed_notes = 0
    folded_notes = 0
    for note in raw_notes:
        pitch = int(note["pitch"])
        new_pitch, folded = _remap_pitch(
            pitch, source_tonic, source_intervals, target_tonic, target_intervals
        )
        if new_pitch != pitch:
            changed_notes += 1
        if folded:
            folded_notes += 1
        edited = dict(note)
        edited["pitch"] = new_pitch
        remapped.append(edited)

    remapped.sort(key=lambda item: (float(item["start_time"]), item["pitch"]))

    return {
        "read_only": True,
        "source_tonic_pitch_class": source_tonic,
        "source_scale": source_name,
        "target_tonic_pitch_class": target_tonic,
        "target_scale": target_name,
        "degree_count": len(source_intervals),
        "note_count": len(remapped),
        "changed_notes": changed_notes,
        "folded_notes": folded_notes,
        "source_fingerprint": _fingerprint(raw_notes, length),
        "length_beats": length,
        "notes": remapped,
    }
