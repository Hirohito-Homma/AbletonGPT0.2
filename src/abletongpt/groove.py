"""Shape a MIDI clip's note velocities: crescendo, dynamic range, and groove accents.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_velocity_groove_plan`
changes only note velocities via three independent, composable operations:

* ``crescendo`` (-1..1) -- a velocity ramp across the clip over time (+1 quiet->loud, -1 loud->quiet).
* ``dynamics`` (-1..1) -- scale each velocity's distance from the clip mean: negative compresses
  the dynamic range toward the mean, positive expands it away from the mean.
* ``accent_pattern`` + ``grid_beats`` -- a cyclic list of multipliers applied per grid step, for a
  groove/accent template (e.g. ``[1.15, 0.9, 1.0, 0.9]``).

This is macro-dynamics shaping and is deliberately distinct from :mod:`abletongpt.expression`,
which does metric downbeat accents, swing and random humanization. Pitch/timing/duration/
probability are preserved, the note count never changes, and velocities are clamped to 1..127.

Deterministic and read-only: the server tool writes the result back through the same undoable
``apply_expression_to_clip`` path the other MIDI editors use.
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_NOTES = 4096
_MAX_PATTERN = 64
_CRESCENDO_DEPTH = 0.5  # crescendo=+/-1 ramps the velocity multiplier over 1 +/- this


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


def build_velocity_groove_plan(
    clip_data: dict[str, Any],
    crescendo: float = 0.0,
    dynamics: float = 0.0,
    accent_pattern: list[float] | None = None,
    grid_beats: float = 1.0,
) -> dict[str, Any]:
    """Return a read-only plan that reshapes ``clip_data``'s velocities (see module docstring).

    Only ``velocity`` changes; timing/pitch/duration/probability are preserved and the note count
    is unchanged. Velocities are clamped to 1..127. Pipeline per note: dynamics (spread about the
    mean) -> crescendo (time ramp) -> accent pattern (grid step) -> clamp/round.
    """
    crescendo = float(crescendo)
    dynamics = float(dynamics)
    grid_beats = float(grid_beats)
    pattern = list(accent_pattern) if accent_pattern else []
    if not -1.0 <= crescendo <= 1.0:
        raise ValueError("crescendo must be between -1 and 1")
    if not -1.0 <= dynamics <= 1.0:
        raise ValueError("dynamics must be between -1 and 1")
    if grid_beats <= 0.0:
        raise ValueError("grid_beats must be greater than 0")
    if len(pattern) > _MAX_PATTERN:
        raise ValueError("accent_pattern may have at most %d steps" % _MAX_PATTERN)
    if any(value < 0.0 for value in pattern):
        raise ValueError("accent_pattern values must be non-negative multipliers")

    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("clip length must be between 0 and 4096 beats")
    raw_notes = clip_data.get("notes", [])
    if not raw_notes:
        raise ValueError("source MIDI clip contains no notes")
    if len(raw_notes) > _MAX_NOTES:
        raise ValueError("a clip may contain at most %d notes" % _MAX_NOTES)

    velocities = [float(note.get("velocity", 100)) for note in raw_notes]
    mean_velocity = sum(velocities) / len(velocities)
    spread_factor = 1.0 + dynamics  # -1 -> 0 (collapse to mean), +1 -> 2 (double the deviation)

    shaped: list[dict[str, Any]] = []
    changed_notes = 0
    max_delta = 0
    for note, source_velocity in zip(raw_notes, velocities):
        value = mean_velocity + (source_velocity - mean_velocity) * spread_factor

        if crescendo:
            position = float(note["start_time"]) / length  # 0..1 across the clip
            value *= 1.0 + crescendo * _CRESCENDO_DEPTH * (2.0 * position - 1.0)

        if pattern:
            step = int(float(note["start_time"]) // grid_beats)
            value *= pattern[step % len(pattern)]

        new_velocity = int(round(value))
        new_velocity = min(127, max(1, new_velocity))
        original_velocity = int(round(source_velocity))
        if new_velocity != original_velocity:
            changed_notes += 1
            max_delta = max(max_delta, abs(new_velocity - original_velocity))

        edited = dict(note)
        edited["velocity"] = new_velocity
        shaped.append(edited)

    shaped.sort(key=lambda item: (float(item["start_time"]), int(item["pitch"])))
    result_velocities = [note["velocity"] for note in shaped]

    return {
        "read_only": True,
        "crescendo": crescendo,
        "dynamics": dynamics,
        "accent_pattern": pattern,
        "grid_beats": grid_beats,
        "note_count": len(shaped),
        "changed_notes": changed_notes,
        "max_velocity_delta": max_delta,
        "source_velocity_range": {"min": int(min(velocities)), "max": int(max(velocities))},
        "result_velocity_range": {"min": min(result_velocities), "max": max(result_velocities)},
        "source_fingerprint": _fingerprint(raw_notes, length),
        "length_beats": length,
        "notes": shaped,
    }
