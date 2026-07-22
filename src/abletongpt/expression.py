"""Deterministic expressive editing of an existing MIDI clip.

This is a pure logic engine: it reads a MIDI clip (the same ``{length_beats, notes}``
shape :mod:`abletongpt.contextual` consumes) and returns a *plan* describing a more
expressively performed version of the same notes -- metric velocity accents, swing,
timing/velocity humanization and weak-beat note probability. It is **read-only**: it
never mutates the source, opens a socket or touches Ableton. Applying the plan to a
Live clip is a separate, explicitly approved step (plan/create split).

Given a ``seed`` the result is fully reproducible, so the same clip and settings always
yield the same performance -- change the seed for a different humanized take.

It can also generate a MIDI CC automation envelope (a shaped breakpoint curve over the
clip timeline) alongside the notes, so a single plan describes both the performed notes
and the clip's automation.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from typing import Any

#: Hard ceiling on notes accepted from a source clip (mirrors ``contextual``).
_MAX_NOTES = 4096

#: Automation envelope shapes, all faithful under Live's linear breakpoint interpolation.
AUTOMATION_SHAPES = ("ramp_up", "ramp_down", "arch", "sine")

#: Human names for the common MIDI CC controllers, for readable plans.
_CC_NAMES = {
    1: "Mod Wheel",
    7: "Volume",
    10: "Pan",
    11: "Expression",
    71: "Resonance",
    74: "Filter Cutoff",
    91: "Reverb Send",
    93: "Chorus Send",
}

#: Largest absolute timing jitter, in beats, at ``humanize == 1.0``.
_HUMANIZE_TIMING_BEATS = 0.025

#: Largest absolute velocity jitter at ``humanize == 1.0``.
_HUMANIZE_VELOCITY = 9

#: Velocity added/removed at ``accent == 1.0`` by metric position.
_ACCENT_DOWNBEAT = 24
_ACCENT_ONBEAT = 12
_ACCENT_OFFBEAT = 10

#: Fraction of a grid step an off-grid note is delayed at ``swing == 1.0``.
_SWING_FRACTION = 0.5


def build_expression_plan(
    clip_data: dict[str, Any],
    *,
    accent: float = 0.0,
    swing: float = 0.0,
    humanize: float = 0.0,
    weak_beat_probability: float = 1.0,
    beats_per_bar: int = 4,
    grid_beats: float = 0.5,
    automation_shape: str | None = None,
    automation_cc: int = 1,
    automation_depth: int = 64,
    automation_base: int = 0,
    automation_cycles: int = 1,
    automation_resolution_beats: float = 0.25,
    seed: int = 0,
) -> dict[str, Any]:
    """Return a read-only expressive performance plan for ``clip_data``'s notes.

    All shaping controls default to a no-op, so an unconfigured call returns the source
    notes unchanged (bar the deterministic re-sort). Each control is independent:

    * ``accent`` -- boost downbeats/on-beats and soften off-beats by velocity.
    * ``swing`` -- delay off-grid notes toward the following grid line.
    * ``humanize`` -- add seeded timing and velocity jitter.
    * ``weak_beat_probability`` -- lower per-note probability on off-grid notes only.
    * ``automation_shape`` -- when set, also emit one MIDI CC envelope over the clip.
    """
    length = _validate(
        clip_data, accent, swing, humanize, weak_beat_probability, beats_per_bar, grid_beats
    )
    source = _normalized_notes(clip_data.get("notes", []), length)
    if not source:
        raise ValueError("source MIDI clip contains no notes")

    rng = random.Random(seed)
    performed: list[dict[str, Any]] = []
    timing_shifts: list[float] = []
    for original in source:
        edited = _perform_note(
            original,
            accent=accent,
            swing=swing,
            humanize=humanize,
            weak_beat_probability=weak_beat_probability,
            beats_per_bar=beats_per_bar,
            grid_beats=grid_beats,
            length=length,
            rng=rng,
        )
        timing_shifts.append(round(edited["start_time"] - original["start_time"], 5))
        performed.append(edited)

    performed.sort(key=lambda item: (item["start_time"], item["pitch"]))

    automation: list[dict[str, Any]] = []
    if automation_shape is not None:
        automation.append(
            build_automation_envelope(
                length,
                shape=automation_shape,
                controller=automation_cc,
                depth=automation_depth,
                base=automation_base,
                cycles=automation_cycles,
                resolution_beats=automation_resolution_beats,
            )
        )

    diff = _summarize(source, performed, timing_shifts)
    diff["automation_envelopes"] = len(automation)
    return {
        "read_only": True,
        "source": {
            "length_beats": length,
            "track": clip_data.get("track"),
            "note_count": len(source),
            "fingerprint": _fingerprint(source, length),
        },
        "settings": {
            "accent": accent,
            "swing": swing,
            "humanize": humanize,
            "weak_beat_probability": weak_beat_probability,
            "beats_per_bar": beats_per_bar,
            "grid_beats": grid_beats,
            "seed": seed,
        },
        "notes": performed,
        "automation": automation,
        "diff": diff,
        "apply_contract": {
            "requires_confirmation": True,
            "overwrites_clip_notes": True,
            "adds_or_deletes_notes": False,
            "writes_automation_envelopes": bool(automation),
            "target": "one existing MIDI clip",
        },
        "notes_help": [
            "read_only=Trueのため、この計画自体はLiveを一切変更しません。",
            "適用は承認付きの別ステップで、ノート数は変えず表情だけ差し替えます。",
            "seedを変えると、同じ設定のまま別のヒューマナイズ結果になります。",
        ],
    }


def _perform_note(
    original: dict[str, Any],
    *,
    accent: float,
    swing: float,
    humanize: float,
    weak_beat_probability: float,
    beats_per_bar: int,
    grid_beats: float,
    length: float,
    rng: random.Random,
) -> dict[str, Any]:
    """Apply every shaping control to one note and clamp it back into the clip."""
    start = original["start_time"]
    step = round(start / grid_beats)
    is_offbeat = step % 2 == 1
    is_downbeat = abs(start % beats_per_bar) < 1e-6

    velocity = original["velocity"]
    if accent:
        if is_downbeat:
            velocity += accent * _ACCENT_DOWNBEAT
        elif not is_offbeat:
            velocity += accent * _ACCENT_ONBEAT
        else:
            velocity -= accent * _ACCENT_OFFBEAT
    if humanize:
        velocity += rng.uniform(-_HUMANIZE_VELOCITY, _HUMANIZE_VELOCITY) * humanize

    performed_start = start
    if swing and is_offbeat:
        performed_start += swing * grid_beats * _SWING_FRACTION
    if humanize:
        performed_start += rng.uniform(-_HUMANIZE_TIMING_BEATS, _HUMANIZE_TIMING_BEATS) * humanize
    performed_start = min(max(0.0, performed_start), max(0.0, length - 1e-4))

    probability = original["probability"]
    if is_offbeat and weak_beat_probability < 1.0:
        probability = min(probability, weak_beat_probability)

    return {
        "pitch": original["pitch"],
        "start_time": round(performed_start, 5),
        "duration": round(min(original["duration"], length - performed_start), 5),
        "velocity": max(1, min(127, int(round(velocity)))),
        "probability": round(max(0.0, min(1.0, probability)), 4),
    }


def build_automation_envelope(
    length: float,
    *,
    shape: str,
    controller: int = 1,
    depth: int = 64,
    base: int = 0,
    cycles: int = 1,
    resolution_beats: float = 0.25,
) -> dict[str, Any]:
    """Return a deterministic MIDI CC envelope (breakpoints) spanning ``length`` beats.

    ``shape`` is one of :data:`AUTOMATION_SHAPES`; values are sampled every
    ``resolution_beats`` and clamped to 0-127. Pure and read-only.
    """
    if shape not in AUTOMATION_SHAPES:
        raise ValueError(
            "automation shape must be one of %s" % ", ".join(AUTOMATION_SHAPES)
        )
    if not 0 < length <= 4096.0:
        raise ValueError("clip length must be between 0 and 4096 beats")
    if not 0 <= controller <= 127:
        raise ValueError("automation controller (CC) must be between 0 and 127")
    if not 0 <= base <= 127 or not 0 <= depth <= 127:
        raise ValueError("automation base and depth must be between 0 and 127")
    if not 1 <= cycles <= 64:
        raise ValueError("automation cycles must be between 1 and 64")
    if not 0.03125 <= resolution_beats <= length:
        raise ValueError("automation resolution must be between 1/32 beat and the clip length")

    points = []
    steps = max(1, int(round(length / resolution_beats)))
    for index in range(steps + 1):
        time = min(length, index * resolution_beats)
        phase = time / length
        value = _envelope_value(shape, phase, base, depth, cycles)
        points.append({"time": round(time, 5), "value": max(0, min(127, int(round(value))))})
        if time >= length:
            break
    return {
        "type": "midi_cc",
        "controller": controller,
        "controller_name": _CC_NAMES.get(controller),
        "shape": shape,
        "point_count": len(points),
        "points": points,
    }


def _envelope_value(shape: str, phase: float, base: int, depth: int, cycles: int) -> float:
    """Envelope value at ``phase`` in [0, 1] for the given shape."""
    if shape == "ramp_up":
        return base + depth * phase
    if shape == "ramp_down":
        return base + depth * (1.0 - phase)
    if shape == "arch":
        return base + depth * math.sin(math.pi * phase)
    # "sine": an LFO starting at ``base``, rising first, over ``cycles`` full cycles.
    return base + depth * (0.5 - 0.5 * math.cos(2.0 * math.pi * cycles * phase))


def _summarize(
    source: list[dict[str, Any]],
    performed: list[dict[str, Any]],
    timing_shifts: list[float],
) -> dict[str, Any]:
    """Human/machine-readable before/after summary of the performance."""
    before = [item["velocity"] for item in source]
    after = [item["velocity"] for item in performed]
    abs_shifts = [abs(shift) for shift in timing_shifts]
    return {
        "note_count": len(performed),
        "velocity": {
            "average_before": round(statistics.fmean(before), 2),
            "average_after": round(statistics.fmean(after), 2),
            "range_after": [min(after), max(after)],
        },
        "timing": {
            "max_shift_beats": round(max(abs_shifts), 5),
            "average_shift_beats": round(statistics.fmean(abs_shifts), 5),
        },
        "probability": {
            "minimum_after": round(min(item["probability"] for item in performed), 4),
        },
    }


def _validate(
    clip_data: dict[str, Any],
    accent: float,
    swing: float,
    humanize: float,
    weak_beat_probability: float,
    beats_per_bar: int,
    grid_beats: float,
) -> float:
    """Range-check settings and the clip length; return the validated length."""
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("source clip length must be between 0 and 4096 beats")
    for name, value in (("accent", accent), ("swing", swing), ("humanize", humanize)):
        if not 0.0 <= value <= 1.0:
            raise ValueError("%s must be between 0.0 and 1.0" % name)
    if not 0.0 <= weak_beat_probability <= 1.0:
        raise ValueError("weak_beat_probability must be between 0.0 and 1.0")
    if not 1 <= beats_per_bar <= 16:
        raise ValueError("beats_per_bar must be between 1 and 16")
    if not 0.03125 <= grid_beats <= float(beats_per_bar):
        raise ValueError("grid_beats must be between 1/32 beat and one bar")
    return length


def _normalized_notes(raw_notes: list[dict[str, Any]], length: float) -> list[dict[str, Any]]:
    """Coerce raw note dicts into the canonical shape, rejecting out-of-clip notes.

    Kept independent from :mod:`abletongpt.contextual` so the engines stay decoupled;
    the accepted schema (``pitch/start_time/duration/velocity/probability``) is identical.
    """
    if not isinstance(raw_notes, list) or len(raw_notes) > _MAX_NOTES:
        raise ValueError("source notes must be a list containing at most 4096 notes")
    normalized = []
    for raw in raw_notes:
        pitch = int(raw["pitch"])
        start = float(raw["start_time"])
        duration = float(raw["duration"])
        velocity = int(raw.get("velocity", 100))
        probability = float(raw.get("probability", 1.0))
        if not 0 <= pitch <= 127 or not 0.0 <= start < length or duration <= 0.0:
            raise ValueError("source note is outside the MIDI clip")
        normalized.append(
            {
                "pitch": pitch,
                "start_time": start,
                "duration": min(duration, length - start),
                "velocity": max(1, min(127, velocity)),
                "probability": max(0.0, min(1.0, probability)),
            }
        )
    return sorted(normalized, key=lambda item: (item["start_time"], item["pitch"]))


def _fingerprint(notes: list[dict[str, Any]], length: float) -> str:
    """Stable short hash of the source notes, so ``apply`` can detect edits since plan.

    Uses the same scheme as :mod:`abletongpt.contextual` for a consistent identity.
    """
    compact = [
        [
            item["pitch"],
            round(item["start_time"], 5),
            round(item["duration"], 5),
            item["velocity"],
            round(item["probability"], 5),
        ]
        for item in notes
    ]
    payload = json.dumps({"length": round(length, 5), "notes": compact}, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
