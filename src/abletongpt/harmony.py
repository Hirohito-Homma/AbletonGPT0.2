"""Harmonic-mixing key compatibility on the Camelot wheel.

Pure logic, stdlib only -- no Live connection and no NumPy. Turns key names (the ``"C major"`` /
``"A minor"`` shape :func:`abletongpt.audio.estimate_key` returns, plus common shorthands and
Camelot codes) into Camelot-wheel positions and reports how well two keys mix harmonically:
same key, relative major/minor, an adjacent step (a perfect fifth/fourth), a whole-tone
"energy" move, or a clash. Deterministic and read-only -- it describes the relationship and a
0-100 compatibility score, it never transposes anything.

The Camelot wheel lays the 24 keys on a clock by the circle of fifths: the outer ``B`` ring is
major, the inner ``A`` ring is minor, and a key sits next to its relative (``8A`` A minor shares
``8B`` C major) and its neighbours a fifth away (``8B`` C major next to ``9B`` G major and
``7B`` F major).
"""

from __future__ import annotations

import re
from typing import Any

# Pitch classes, index 0 == C. Sharps match audio.estimate_key / Live; flats are accepted on input.
_NOTE_TO_PC = {
    "C": 0, "B#": 0,
    "C#": 1, "DB": 1,
    "D": 2,
    "D#": 3, "EB": 3,
    "E": 4, "FB": 4,
    "F": 5, "E#": 5,
    "F#": 6, "GB": 6,
    "G": 7,
    "G#": 8, "AB": 8,
    "A": 9,
    "A#": 10, "BB": 10,
    "B": 11, "CB": 11,
}
_PC_TO_NOTE = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _camelot_number(pc: int, mode: str) -> int:
    """Camelot clock number (1..12) for a pitch class + mode, laid out by the circle of fifths."""
    # A minor key sits at its relative major's position (relative major = minor tonic + 3 semitones).
    reference_pc = pc if mode == "major" else (pc + 3) % 12
    return ((reference_pc * 7 + 7) % 12) + 1


def camelot_code(pc: int, mode: str) -> str:
    """Return the Camelot code (e.g. ``"8B"`` for C major, ``"8A"`` for A minor)."""
    return "%d%s" % (_camelot_number(pc, mode), "B" if mode == "major" else "A")


# Reverse lookup built from the forward mapping so the two can never drift apart.
_CODE_TO_KEY: dict[str, tuple[int, str]] = {}
for _pc in range(12):
    for _mode in ("major", "minor"):
        _CODE_TO_KEY[camelot_code(_pc, _mode)] = (_pc, _mode)


def parse_key(text: str) -> tuple[int, str]:
    """Parse a key into ``(pitch_class, mode)``.

    Accepts ``"C major"`` / ``"A minor"`` (estimate_key's shape), shorthands (``"C"`` = major,
    ``"Am"``, ``"F#m"``), flats (``"Db minor"``) and Camelot codes (``"8A"``, ``"12B"``).
    Raises :class:`ValueError` on anything unrecognized.
    """
    token = text.strip()
    if not token:
        raise ValueError("empty key")

    camelot = re.fullmatch(r"(\d{1,2})\s*([ABab])", token)
    if camelot:
        number = int(camelot.group(1))
        letter = camelot.group(2).upper()
        code = "%d%s" % (number, letter)
        if code not in _CODE_TO_KEY:
            raise ValueError("invalid Camelot code %r (numbers are 1-12)" % token)
        return _CODE_TO_KEY[code]

    match = re.fullmatch(r"([A-Ga-g][#b]?)\s*(.*)", token)
    if not match:
        raise ValueError("unrecognized key %r" % text)
    note = match.group(1)
    pc = _NOTE_TO_PC.get(note.upper())
    if pc is None:
        raise ValueError("unrecognized note in key %r" % text)

    mode_text = match.group(2).strip().lower()
    if mode_text in ("", "maj", "major", "M"):
        mode = "major"
    elif mode_text in ("m", "min", "minor"):
        mode = "minor"
    else:
        raise ValueError("unrecognized mode in key %r" % text)
    return pc, mode


def _key_view(pc: int, mode: str) -> dict[str, Any]:
    return {
        "key": "%s %s" % (_PC_TO_NOTE[pc], mode),
        "tonic": _PC_TO_NOTE[pc],
        "mode": mode,
        "camelot": camelot_code(pc, mode),
    }


def _wheel_distance(number_a: int, number_b: int) -> int:
    """Shortest number of steps between two Camelot clock numbers (0..6)."""
    direct = abs(number_a - number_b) % 12
    return min(direct, 12 - direct)


def build_key_compatibility(key_a: str, key_b: str) -> dict[str, Any]:
    """Report how harmonically compatible two keys are on the Camelot wheel (read-only)."""
    pc_a, mode_a = parse_key(key_a)
    pc_b, mode_b = parse_key(key_b)
    view_a = _key_view(pc_a, mode_a)
    view_b = _key_view(pc_b, mode_b)

    number_a = _camelot_number(pc_a, mode_a)
    number_b = _camelot_number(pc_b, mode_b)
    distance = _wheel_distance(number_a, number_b)
    same_ring = mode_a == mode_b

    if same_ring and distance == 0:
        relationship, score = "identical", 100
        note = "Identical key -- fully compatible."
    elif not same_ring and distance == 0:
        relationship, score = "relative", 92
        note = "Relative major/minor -- same notes, different mood; a very smooth blend."
    elif same_ring and distance == 1:
        relationship, score = "adjacent", 88
        note = "Adjacent on the wheel (a perfect fifth/fourth apart) -- a classic harmonic match."
    elif same_ring and distance == 2:
        relationship, score = "two-step", 65
        note = "Two steps on the wheel (a whole tone) -- an energy-boost mix; usable but less smooth."
    elif not same_ring and distance == 1:
        relationship, score = "diagonal", 60
        note = "Diagonal move (the relative of an adjacent key) -- can work, use sparingly."
    else:
        relationship = "distant"
        # Score falls off with wheel distance; distant keys clash harmonically.
        score = max(10, 55 - (distance - 2) * 10)
        note = (
            "%d steps apart on the wheel -- not a harmonic match; only as a deliberate energy jump."
            % distance
        )

    return {
        "read_only": True,
        "a": view_a,
        "b": view_b,
        "camelot_distance": distance,
        "relationship": relationship,
        "compatible": score >= 70,
        "score": score,
        "guidance": [note],
    }


def suggest_compatible_keys(key: str) -> dict[str, Any]:
    """List the keys that mix well with ``key`` (same, relative, and the two adjacent fifths)."""
    pc, mode = parse_key(key)
    number = _camelot_number(pc, mode)
    letter = "B" if mode == "major" else "A"
    other_letter = "A" if letter == "B" else "B"

    def _entry(code: str, relationship: str) -> dict[str, Any]:
        neighbour_pc, neighbour_mode = _CODE_TO_KEY[code]
        entry = _key_view(neighbour_pc, neighbour_mode)
        entry["relationship"] = relationship
        return entry

    up = (number % 12) + 1
    down = ((number - 2) % 12) + 1
    return {
        "read_only": True,
        "key": _key_view(pc, mode),
        "compatible": [
            _entry("%d%s" % (number, letter), "identical"),
            _entry("%d%s" % (number, other_letter), "relative"),
            _entry("%d%s" % (up, letter), "adjacent (+1, up a fifth)"),
            _entry("%d%s" % (down, letter), "adjacent (-1, down a fifth)"),
        ],
    }
