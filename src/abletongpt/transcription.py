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
