"""Turn offline audio analysis into editable MIDI clip plans.

Pure logic, stdlib only -- no Live connection and no NumPy. It bridges the read-only audio
analysers in :mod:`abletongpt.audio` and the existing ``create_midi_clip`` mutation:
:func:`build_midi_from_melody` converts an ``extract_melody`` result plus a tempo into notes
in musical beats, ready to hand to ``create_midi_clip``. Deterministic and testable in
isolation with a hand-built melody dict -- the NumPy-heavy extraction stays in the server tool.
"""

from __future__ import annotations

import math
from typing import Any

# Pitch-class of each root name that :func:`abletongpt.audio.estimate_chords` emits.
_NOTE_TO_PC = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}


def build_midi_from_melody(
    melody: dict[str, Any],
    tempo: float,
    *,
    quantize: float = 0.0,
    velocity: int = 100,
) -> dict[str, Any]:
    """Convert an ``extract_melody`` result + tempo (BPM) into a ``create_midi_clip`` plan.

    Note times in seconds become musical beats via ``tempo``. ``quantize`` (in beats, e.g.
    ``0.25`` for 1/16 notes; ``0`` disables) snaps note starts and ends to a grid. The clip
    length is rounded up to the next whole beat. Returns notes in the ``create_midi_clip``
    format (``pitch``/``start_time``/``duration``/``velocity``, all in beats).
    """
    if tempo <= 0.0:
        raise ValueError("tempo must be positive")
    if not 0.0 <= quantize <= 16.0:
        raise ValueError("quantize must be between 0 and 16 beats")
    if not 1 <= velocity <= 127:
        raise ValueError("velocity must be between 1 and 127")

    beats_per_second = tempo / 60.0
    notes: list[dict[str, Any]] = []
    for source in melody.get("notes", []):
        start = float(source["start_seconds"]) * beats_per_second
        end = float(source["end_seconds"]) * beats_per_second
        if quantize > 0.0:
            start = round(start / quantize) * quantize
            end = round(end / quantize) * quantize
            if end <= start:
                end = start + quantize
        duration = end - start
        if duration <= 0.0:
            continue
        notes.append(
            {
                "pitch": int(source["midi"]),
                "start_time": round(start, 6),
                "duration": round(duration, 6),
                "velocity": velocity,
            }
        )

    last_end = max((note["start_time"] + note["duration"] for note in notes), default=0.0)
    length_beats = float(max(1, math.ceil(last_end)))

    return {
        "source": "melody",
        "tempo": tempo,
        "quantize": quantize,
        "length_beats": length_beats,
        "notes": notes,
        "note_count": len(notes),
    }


def build_midi_from_times(
    times: list[float],
    tempo: float,
    *,
    pitch: int = 36,
    velocity: int = 100,
    duration_beats: float = 0.25,
    quantize: float = 0.0,
    strengths: list[float] | None = None,
) -> dict[str, Any]:
    """Convert a list of event times (seconds) + tempo into a ``create_midi_clip`` plan.

    Each time becomes one short note at a single ``pitch`` -- a trigger for detected onsets
    or beats. When ``strengths`` (0-1 per time) is given, velocity scales from 40% to 100% of
    ``velocity`` for accents. ``quantize`` snaps note starts to a beat grid; notes that then
    collapse onto the same start are merged, keeping the louder one.
    """
    if tempo <= 0.0:
        raise ValueError("tempo must be positive")
    if not 0 <= pitch <= 127:
        raise ValueError("pitch must be between 0 and 127")
    if not 1 <= velocity <= 127:
        raise ValueError("velocity must be between 1 and 127")
    if not 0.0 < duration_beats <= 16.0:
        raise ValueError("duration_beats must be between 0 and 16")
    if not 0.0 <= quantize <= 16.0:
        raise ValueError("quantize must be between 0 and 16 beats")

    beats_per_second = tempo / 60.0
    by_start: dict[float, dict[str, Any]] = {}
    for index, time in enumerate(times):
        start = float(time) * beats_per_second
        if quantize > 0.0:
            start = round(start / quantize) * quantize
        start = round(start, 6)
        note_velocity = velocity
        if strengths is not None and index < len(strengths):
            strength = max(0.0, min(1.0, float(strengths[index])))
            note_velocity = max(1, min(127, int(round((0.4 + 0.6 * strength) * velocity))))
        existing = by_start.get(start)
        if existing is None or note_velocity > existing["velocity"]:
            by_start[start] = {
                "pitch": pitch,
                "start_time": start,
                "duration": round(duration_beats, 6),
                "velocity": note_velocity,
            }

    notes = [by_start[start] for start in sorted(by_start)]
    last_end = max((note["start_time"] + note["duration"] for note in notes), default=0.0)
    length_beats = float(max(1, math.ceil(last_end)))

    return {
        "source": "times",
        "tempo": tempo,
        "quantize": quantize,
        "pitch": pitch,
        "length_beats": length_beats,
        "notes": notes,
        "note_count": len(notes),
    }


def build_locators_from_structure(
    structure: dict[str, Any],
    tempo: float,
    *,
    include_end: bool = False,
) -> dict[str, Any]:
    """Convert a ``segment_structure`` result + tempo into Arrangement-locator positions.

    Each section start becomes a named locator (``"1 A"``, ``"2 B"`` ...) positioned in
    musical beats via ``tempo``. With ``include_end`` a final ``"End"`` locator is added at
    the last section's end. Times are relative to the Arrangement start, so this assumes the
    analysed audio plays from bar 1 at ``tempo``.
    """
    if tempo <= 0.0:
        raise ValueError("tempo must be positive")

    beats_per_second = tempo / 60.0
    locators: list[dict[str, Any]] = []
    segments = structure.get("segments", [])
    for index, segment in enumerate(segments):
        start = float(segment["start_seconds"])
        locators.append(
            {
                "name": "%d %s" % (index + 1, segment.get("label", "?")),
                "time_seconds": round(start, 4),
                "time_beats": round(start * beats_per_second, 6),
            }
        )
    if include_end and segments:
        end = float(segments[-1]["end_seconds"])
        locators.append(
            {
                "name": "End",
                "time_seconds": round(end, 4),
                "time_beats": round(end * beats_per_second, 6),
            }
        )

    return {"tempo": tempo, "locators": locators, "count": len(locators)}


def _parse_chord(label: str):
    """Parse a chord label like ``C``/``Cm``/``F#`` into ``(root_pc, quality)`` or ``None``.

    ``None`` for the no-chord label ``"N"``. Only the major/minor triad labels emitted by
    :func:`abletongpt.audio.estimate_chords` are recognised.
    """
    if label == "N":
        return None
    quality = "minor" if label.endswith("m") else "major"
    root_name = label[:-1] if quality == "minor" else label
    pitch_class = _NOTE_TO_PC.get(root_name)
    if pitch_class is None:
        raise ValueError("unrecognised chord label: %s" % label)
    return pitch_class, quality


def build_midi_from_chords(
    chords: dict[str, Any],
    tempo: float,
    *,
    octave: int = 3,
    velocity: int = 100,
    quantize: float = 0.0,
) -> dict[str, Any]:
    """Convert an ``estimate_chords`` result + tempo (BPM) into a ``create_midi_clip`` plan.

    Each detected chord segment becomes a block triad (root/third/fifth) held for the
    segment's duration, with the root at ``octave`` (``octave=3`` puts C at MIDI 48). No-chord
    (``"N"``) segments are skipped. ``quantize`` snaps segment starts/ends to a beat grid.
    """
    if tempo <= 0.0:
        raise ValueError("tempo must be positive")
    if not 0 <= octave <= 8:
        raise ValueError("octave must be between 0 and 8")
    if not 0.0 <= quantize <= 16.0:
        raise ValueError("quantize must be between 0 and 16 beats")
    if not 1 <= velocity <= 127:
        raise ValueError("velocity must be between 1 and 127")

    beats_per_second = tempo / 60.0
    notes: list[dict[str, Any]] = []
    chords_used = 0
    for segment in chords.get("chords", []):
        parsed = _parse_chord(segment["chord"])
        if parsed is None:
            continue
        pitch_class, quality = parsed
        start = float(segment["start_seconds"]) * beats_per_second
        end = float(segment["end_seconds"]) * beats_per_second
        if quantize > 0.0:
            start = round(start / quantize) * quantize
            end = round(end / quantize) * quantize
            if end <= start:
                end = start + quantize
        duration = end - start
        if duration <= 0.0:
            continue
        root = 12 * (octave + 1) + pitch_class
        third = root + (3 if quality == "minor" else 4)
        fifth = root + 7
        chords_used += 1
        for pitch in (root, third, fifth):
            if 0 <= pitch <= 127:
                notes.append(
                    {
                        "pitch": pitch,
                        "start_time": round(start, 6),
                        "duration": round(duration, 6),
                        "velocity": velocity,
                    }
                )

    last_end = max((note["start_time"] + note["duration"] for note in notes), default=0.0)
    length_beats = float(max(1, math.ceil(last_end)))

    return {
        "source": "chords",
        "tempo": tempo,
        "quantize": quantize,
        "octave": octave,
        "length_beats": length_beats,
        "notes": notes,
        "note_count": len(notes),
        "chord_count": chords_used,
    }
