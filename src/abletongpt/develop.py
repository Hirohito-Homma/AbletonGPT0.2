"""Develop one MIDI loop into a *narrative* arrangement -- the same material, told as a story.

Pure logic, stdlib only -- no Live connection and no NumPy. Where :mod:`phrase` tiles a loop into a
longer clip *verbatim*, this reads the narrative arc for a song structure
(:func:`narrative.build_narrative_arc`) and rebuilds the loop **differently in every section**,
following each section's change directives: a sparse filtered intro, verses that vary each time
they return, a build that ramps and fills into the chorus, a full chorus with an octave-doubled
top, an intimate breakdown that drops the low voices, and so on. The transformed sections are laid
end to end into one long clip so a single loop becomes a full arrangement with a beginning, a rise,
a peak and a release.

Because the note count and length change, this is a *create* (a new clip), not an in-place edit --
the server tool writes the result into an empty slot via the non-overwriting ``create_midi_clip``,
exactly like :mod:`phrase` and :mod:`timescale`. Deterministic: the same loop + structure + seed
always yields the same arrangement. Reuses the narrative arc so the development matches the intent
that :func:`narrative.build_narrative_arc` reports.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .narrative import build_narrative_arc

_MAX_NOTES = 8192
_MAX_LENGTH = 8192.0
_MAX_SECTIONS = 32
_MAX_SECTION_REPEATS = 16
_GRID_EPS = 1e-3
_MIN_FILL_DURATION = 0.125  # only subdivide notes at least this long


def _fingerprint(notes: list[dict[str, Any]], length: float) -> str:
    """Stable short hash of the source loop, for the review -> create guard (matches phrase.py)."""
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


def _bar_beats(clip_data: dict[str, Any], loop_length: float) -> float:
    signature = clip_data.get("time_signature") or [4, 4]
    numerator = int(signature[0]) if signature else 4
    denominator = int(signature[1]) if len(signature) > 1 else 4
    bar = numerator * (4.0 / denominator)
    return min(bar, loop_length)


def _copy(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "pitch": int(note["pitch"]),
        "start_time": round(float(note["start_time"]), 6),
        "duration": round(float(note["duration"]), 6),
        "velocity": int(note.get("velocity", 100)),
        "probability": float(note.get("probability", 1.0)),
    }


def _on_grid(start: float, grid: float) -> bool:
    position = start / grid
    return abs(position - round(position)) < _GRID_EPS


def _tile(notes: list[dict[str, Any]], loop_length: float, repeats: int) -> list[dict[str, Any]]:
    tiled: list[dict[str, Any]] = []
    for repeat in range(repeats):
        offset = repeat * loop_length
        for note in notes:
            edited = _copy(note)
            edited["start_time"] = round(edited["start_time"] + offset, 6)
            tiled.append(edited)
    return tiled


def _median_pitch(notes: list[dict[str, Any]]) -> float:
    pitches = sorted(int(note["pitch"]) for note in notes)
    if not pitches:
        return 60.0
    mid = len(pitches) // 2
    if len(pitches) % 2:
        return float(pitches[mid])
    return (pitches[mid - 1] + pitches[mid]) / 2.0


def _apply_density(notes: list[dict[str, Any]], density: str, section_length: float) -> list[dict[str, Any]]:
    """Thin the loop for low-energy sections; add subdivision fills for high-energy ones."""
    if density == "sparse":
        kept = [note for note in notes if _on_grid(note["start_time"], 1.0)]
        return kept or notes
    if density == "light":
        kept = [note for note in notes if _on_grid(note["start_time"], 0.5)]
        return kept or notes
    if density in ("dense", "full"):
        extra: list[dict[str, Any]] = []
        for note in notes:
            duration = note["duration"]
            if duration < _MIN_FILL_DURATION:
                continue
            mid = note["start_time"] + duration / 2.0
            if mid >= section_length:
                continue
            fill = _copy(note)
            fill["start_time"] = round(mid, 6)
            fill["duration"] = round(min(duration / 2.0, section_length - mid), 6)
            fill["velocity"] = max(1, int(note["velocity"] * 0.85))
            extra.append(fill)
        return notes + extra
    return notes  # medium: unchanged


def _apply_register(
    notes: list[dict[str, Any]], archetype: str, role: str, section_length: float
) -> list[dict[str, Any]]:
    """Chorus/climax gets an octave-doubled top voice; a breakdown drops its low voices."""
    if not notes:
        return notes
    median = _median_pitch(notes)
    if role == "climax" or archetype == "chorus":
        doubled: list[dict[str, Any]] = []
        for note in notes:
            if int(note["pitch"]) >= median and int(note["pitch"]) + 12 <= 127:
                octave = _copy(note)
                octave["pitch"] = int(note["pitch"]) + 12
                octave["velocity"] = max(1, int(note["velocity"] * 0.8))
                doubled.append(octave)
        return notes + doubled
    if archetype == "breakdown":
        kept = [note for note in notes if int(note["pitch"]) >= median]
        return kept or notes
    return notes


def _apply_velocity(
    notes: list[dict[str, Any]], target_velocity: int, dynamics: str, section_length: float
) -> None:
    """Pull velocities toward the section target and shape them by the dynamics directive (in place)."""
    span = section_length or 1.0
    for note in notes:
        blended = 0.5 * note["velocity"] + 0.5 * target_velocity
        if dynamics == "crescendo":
            position = note["start_time"] / span
            blended *= 0.6 + 0.4 * position
        elif dynamics == "pull back":
            position = note["start_time"] / span
            blended *= 1.0 - 0.4 * position
        elif dynamics == "push/peak":
            blended *= 1.08
        note["velocity"] = max(1, min(127, int(round(blended))))


def _apply_variation(notes: list[dict[str, Any]], salt: int) -> list[dict[str, Any]]:
    """Deterministically thin a returning section so it differs from its first appearance."""
    if len(notes) < 8:
        return notes
    ordered = sorted(notes, key=lambda item: (item["start_time"], item["pitch"]))
    drop_at = salt % 7
    kept = [note for index, note in enumerate(ordered) if index % 7 != drop_at]
    return kept or notes


def _apply_motion_fill(
    notes: list[dict[str, Any]], section_length: float, bar: float
) -> list[dict[str, Any]]:
    """Add a density fill on the final bar (a riser/fill into the next section)."""
    fill_start = section_length - bar
    extra: list[dict[str, Any]] = []
    for note in notes:
        if note["start_time"] < fill_start or note["duration"] < _MIN_FILL_DURATION:
            continue
        mid = note["start_time"] + note["duration"] / 2.0
        if mid >= section_length:
            continue
        fill = _copy(note)
        fill["start_time"] = round(mid, 6)
        fill["duration"] = round(min(note["duration"] / 2.0, section_length - mid), 6)
        fill["velocity"] = min(127, int(note["velocity"] * 1.05))
        extra.append(fill)
    return notes + extra


def build_developed_arrangement(
    clip_data: dict[str, Any],
    structure: list[str],
    section_repeats: int = 2,
    seed: int = 0,
) -> dict[str, Any]:
    """Return a read-only plan that develops ``clip_data`` (a loop) into a narrative arrangement.

    ``structure`` is a list of section labels; each section tiles the loop ``section_repeats`` times
    and is then transformed by that section's narrative directives (density / register / velocity /
    variation / motion fill). The sections are concatenated into one long clip. The plan reports the
    per-section boundaries (with the directives applied and note ranges), the total length, the note
    count, and the source fingerprint. Deterministic; never touches Live.
    """
    section_repeats = int(section_repeats)
    if not 1 <= section_repeats <= _MAX_SECTION_REPEATS:
        raise ValueError("section_repeats must be between 1 and %d" % _MAX_SECTION_REPEATS)
    if not structure:
        raise ValueError("structure must contain at least one section label")
    if len(structure) > _MAX_SECTIONS:
        raise ValueError("structure must have at most %d sections" % _MAX_SECTIONS)
    loop_length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < loop_length <= _MAX_LENGTH:
        raise ValueError("clip length must be between 0 and %d beats" % int(_MAX_LENGTH))
    source_notes = clip_data.get("notes", [])
    if not source_notes:
        raise ValueError("source MIDI clip contains no notes")

    section_length = loop_length * section_repeats
    total_length = section_length * len(structure)
    if total_length > _MAX_LENGTH:
        raise ValueError("the arrangement would exceed %d beats; use fewer sections/repeats" % int(_MAX_LENGTH))
    bar = _bar_beats(clip_data, loop_length)

    arc = build_narrative_arc(list(structure))
    seen: dict[str, int] = {}
    all_notes: list[dict[str, Any]] = []
    section_reports: list[dict[str, Any]] = []

    for section in arc["sections"]:
        archetype = section["archetype"]
        directives = section["directives"]
        role = section["role"]
        occurrence = seen.get(archetype, 0)
        seen[archetype] = occurrence + 1

        tile = _tile(source_notes, loop_length, section_repeats)
        tile = _apply_density(tile, directives["density"], section_length)
        tile = _apply_register(tile, archetype, role, section_length)
        _apply_velocity(tile, int(directives["target_velocity"]), directives["dynamics"], section_length)
        if directives["vary"]:
            tile = _apply_variation(tile, seed + section["position"] + occurrence)
        motion = directives["motion"]
        if "fill" in motion or "riser" in motion:
            tile = _apply_motion_fill(tile, section_length, bar)

        offset = section["position"] * section_length
        for note in tile:
            note["start_time"] = round(note["start_time"] + offset, 6)
        tile.sort(key=lambda item: (item["start_time"], item["pitch"]))
        all_notes.extend(tile)

        section_reports.append(
            {
                "position": section["position"],
                "label": section["label"],
                "archetype": archetype,
                "energy": section["energy"],
                "role": role,
                "start_beat": round(offset, 6),
                "end_beat": round(offset + section_length, 6),
                "note_count": len(tile),
                "applied": {
                    "density": directives["density"],
                    "dynamics": directives["dynamics"],
                    "register": directives["register"],
                    "motion": motion,
                    "vary": directives["vary"],
                },
            }
        )

    if len(all_notes) > _MAX_NOTES:
        raise ValueError("the arrangement would exceed %d notes; use fewer sections/repeats" % _MAX_NOTES)
    all_notes.sort(key=lambda item: (item["start_time"], item["pitch"]))

    return {
        "read_only": True,
        "structure": [str(label) for label in structure],
        "section_repeats": section_repeats,
        "seed": int(seed),
        "loop_length_beats": loop_length,
        "section_length_beats": round(section_length, 6),
        "length_beats": round(total_length, 6),
        "shape": arc["shape"],
        "peak_label": arc["peak_label"],
        "energy_curve": arc["energy_curve"],
        "source_note_count": len(source_notes),
        "note_count": len(all_notes),
        "source_fingerprint": _fingerprint(source_notes, loop_length),
        "sections": section_reports,
        "notes": all_notes,
    }
