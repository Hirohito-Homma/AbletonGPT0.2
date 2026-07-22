"""Roman-numeral / functional analysis of a MIDI chord progression.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_progression_analysis`
slices a clip into fixed windows (one bar by default), identifies the chord sounding in each
window by template matching, and labels it with a Roman numeral and a rough harmonic function
(tonic / subdominant / dominant) relative to a key. Read-only: it describes the harmony, it never
changes anything.

Like the key/chord *estimators* it leans on, this is a heuristic, not music-theory ground truth:
chord identification is energy-weighted template matching, functional labels are the textbook
degree->function mapping, and each chord carries a ``confidence`` plus a ``complete`` flag (was a
full triad actually present) so the caller can see where it is guessing.
"""

from __future__ import annotations

from typing import Any

from .scale import SCALE_INTERVALS

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII")

# Chord templates as intervals from the root. Triads first so a bare triad is not over-fit to a
# seventh (a seventh whose 7th is absent is penalised for the missing tone).
_TEMPLATES: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("maj", (0, 4, 7)),
    ("min", (0, 3, 7)),
    ("dim", (0, 3, 6)),
    ("aug", (0, 4, 8)),
    ("dom7", (0, 4, 7, 10)),
    ("maj7", (0, 4, 7, 11)),
    ("min7", (0, 3, 7, 10)),
    ("m7b5", (0, 3, 6, 10)),
    ("dim7", (0, 3, 6, 9)),
)

# Display suffix and whether the numeral is upper-case (major-ish) or lower-case (minor-ish).
_QUALITY = {
    "maj": ("", True),
    "min": ("", False),
    "dim": ("°", False),
    "aug": ("+", True),
    "dom7": ("7", True),
    "maj7": ("maj7", True),
    "min7": ("7", False),
    "m7b5": ("ø7", False),
    "dim7": ("°7", False),
}

# Degree (0-based scale index) -> harmonic function, per mode.
_FUNCTION = {
    "major": ("tonic", "subdominant", "tonic", "subdominant", "dominant", "tonic", "dominant"),
    "minor": ("tonic", "subdominant", "tonic", "subdominant", "dominant", "subdominant", "dominant"),
}


def identify_chord(weights: dict[int, float]) -> dict[str, Any] | None:
    """Best chord for an energy-weighted pitch-class map, or ``None`` when nothing sounds."""
    total = sum(weights.values())
    if total <= 0.0:
        return None
    present = [pc for pc, weight in weights.items() if weight > 1e-9]

    best_key: tuple | None = None
    best: dict[str, Any] | None = None
    for root in present:
        for order, (name, intervals) in enumerate(_TEMPLATES):
            template_pcs = [(root + interval) % 12 for interval in intervals]
            inside = sum(weights.get(pc, 0.0) for pc in template_pcs)
            outside = total - inside
            matched = sum(1 for pc in template_pcs if weights.get(pc, 0.0) > 1e-9)
            missing = len(intervals) - matched
            score = inside - outside - 0.1 * missing
            candidate = (round(score, 9), matched, -len(intervals), -order)
            if best_key is None or candidate > best_key:
                best_key = candidate
                best = {
                    "root": root,
                    "quality": name,
                    "matched_tones": matched,
                    "complete": matched >= 3,
                    "confidence": round(inside / total, 3),
                }
    return best


def _roman_numeral(root: int, quality: str, tonic: int, mode: str) -> tuple[str, int | None, str]:
    """Return ``(roman, degree_index_or_None, function)`` for a chord root in a key."""
    scale = SCALE_INTERVALS[mode]
    rel = (root - tonic) % 12

    degree: int | None = None
    accidental = ""
    if rel in scale:
        degree = scale.index(rel)
    elif (rel + 1) % 12 in scale:
        degree = scale.index((rel + 1) % 12)
        accidental = "b"
    elif (rel - 1) % 12 in scale:
        degree = scale.index((rel - 1) % 12)
        accidental = "#"

    suffix, upper = _QUALITY[quality]
    if degree is None:
        return "?" + suffix, None, "chromatic"

    numeral = _NUMERALS[degree]
    numeral = numeral if upper else numeral.lower()
    function = "chromatic" if accidental else _FUNCTION[mode][degree]
    return accidental + numeral + suffix, degree, function


def _window_weights(notes: list[dict[str, Any]], start: float, end: float) -> dict[int, float]:
    """Pitch-class -> energy (overlap-with-window * velocity) for one time window."""
    weights: dict[int, float] = {}
    for note in notes:
        note_start = float(note["start_time"])
        note_end = note_start + float(note["duration"])
        overlap = min(note_end, end) - max(note_start, start)
        if overlap <= 0.0:
            continue
        weight = overlap * (float(note.get("velocity", 100)) / 127.0)
        pc = int(note["pitch"]) % 12
        weights[pc] = weights.get(pc, 0.0) + weight
    return weights


def build_progression_analysis(
    clip_data: dict[str, Any],
    tonic: int,
    mode: str,
    segment_beats: float,
) -> dict[str, Any]:
    """Analyze ``clip_data`` window-by-window into Roman numerals + functions in the given key."""
    if mode not in _FUNCTION:
        raise ValueError("mode must be 'major' or 'minor'")
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("clip length must be between 0 and 4096 beats")
    if not 0.0 < segment_beats <= length:
        raise ValueError("segment_beats must be greater than 0 and no larger than the clip length")
    notes = clip_data.get("notes", [])
    if not notes:
        raise ValueError("source MIDI clip contains no notes")

    tonic %= 12
    segments: list[dict[str, Any]] = []
    index = 0
    start = 0.0
    while start < length - 1e-9:
        end = min(start + segment_beats, length)
        chord = identify_chord(_window_weights(notes, start, end))
        entry: dict[str, Any] = {
            "index": index,
            "start_beat": round(start, 4),
            "end_beat": round(end, 4),
        }
        if chord is None:
            entry.update({"chord": None, "roman": None, "function": "rest"})
        else:
            root_name = _NOTE_NAMES[chord["root"]]
            suffix = _QUALITY[chord["quality"]][0]
            roman, _degree, function = _roman_numeral(chord["root"], chord["quality"], tonic, mode)
            entry.update(
                {
                    "chord": root_name + suffix,
                    "root": root_name,
                    "quality": chord["quality"],
                    "roman": roman,
                    "function": function,
                    "complete": chord["complete"],
                    "confidence": chord["confidence"],
                }
            )
        segments.append(entry)
        index += 1
        start += segment_beats

    # Merge consecutive identical romans into a compact progression summary.
    romans: list[str] = []
    for segment in segments:
        label = segment["roman"] if segment["roman"] is not None else "·"  # middle dot = rest
        if not romans or romans[-1] != label:
            romans.append(label)

    return {
        "read_only": True,
        "key": "%s %s" % (_NOTE_NAMES[tonic], mode),
        "tonic": _NOTE_NAMES[tonic],
        "mode": mode,
        "segment_beats": segment_beats,
        "segment_count": len(segments),
        "segments": segments,
        "romans": romans,
        "progression": " - ".join(romans),
    }
