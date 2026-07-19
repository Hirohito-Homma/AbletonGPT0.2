from __future__ import annotations

import random
from typing import Any


PITCH_CLASSES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
}

MOOD_PROGRESSIONS = {
    "bright": [0, 4, 5, 3],
    "uplifting": [0, 3, 4, 0],
    "chill": [0, 5, 3, 4],
    "dark": [0, 5, 2, 6],
    "bittersweet": [5, 3, 0, 4],
    "tense": [0, 1, 5, 4],
}

GENRE_PROFILES = {
    "pop": {
        "bass_step": 1.0,
        "kick": [0.0, 2.5],
        "snare": [1.0, 3.0],
        "hat_step": 0.5,
        "hat_pitch": 42,
        "drum_velocity": 1.0,
    },
    "rock": {
        "bass_step": 1.0,
        "kick": [0.0, 2.0, 2.5],
        "snare": [1.0, 3.0],
        "hat_step": 0.5,
        "hat_pitch": 42,
        "drum_velocity": 1.08,
    },
    "edm": {
        "bass_step": 0.5,
        "kick": [0.0, 1.0, 2.0, 3.0],
        "snare": [1.0, 3.0],
        "hat_step": 0.5,
        "hat_pitch": 42,
        "drum_velocity": 1.06,
    },
    "hiphop": {
        "bass_step": 2.0,
        "kick": [0.0, 1.75, 2.5],
        "snare": [1.0, 3.0],
        "hat_step": 0.25,
        "hat_pitch": 42,
        "drum_velocity": 0.96,
    },
    "rnb": {
        "bass_step": 2.0,
        "kick": [0.0, 2.5],
        "snare": [1.0, 3.0],
        "hat_step": 0.5,
        "hat_pitch": 42,
        "drum_velocity": 0.92,
    },
    "jazz": {
        "bass_step": 1.0,
        "kick": [0.0, 2.0],
        "snare": [1.0, 3.0],
        "hat_step": 0.5,
        "hat_pitch": 51,
        "drum_velocity": 0.78,
    },
    "lofi": {
        "bass_step": 2.0,
        "kick": [0.0, 2.5],
        "snare": [1.0, 3.0],
        "hat_step": 0.5,
        "hat_pitch": 42,
        "drum_velocity": 0.72,
    },
}

CHORD_SIZES = {"triad": 3, "seventh": 4, "ninth": 5}


def note(
    pitch: int,
    start: float,
    duration: float,
    velocity: int,
    probability: float = 1.0,
) -> dict[str, Any]:
    return {
        "pitch": max(0, min(127, int(pitch))),
        "start_time": round(max(0.0, start), 5),
        "duration": round(max(0.02, duration), 5),
        "velocity": max(1, min(127, int(velocity))),
        "probability": max(0.0, min(1.0, probability)),
    }


def build_song_plan(
    title: str,
    genre: str,
    mood: str,
    key: str,
    mode: str,
    tempo: float,
    bars: int,
    progression: list[int] | None = None,
    chord_complexity: str = "triad",
    harmonic_rhythm_beats: float = 4.0,
    melody_density: float = 0.75,
    swing: float = 0.0,
    humanize: float = 0.0,
    seed: int = 0,
) -> dict[str, Any]:
    _validate_options(
        genre, mood, key, mode, tempo, bars, progression, chord_complexity,
        harmonic_rhythm_beats, melody_density, swing, humanize,
    )
    rng = random.Random(seed)
    root_pc = PITCH_CLASSES[key]
    scale = SCALES[mode]
    degrees = (
        [degree - 1 for degree in progression]
        if progression
        else MOOD_PROGRESSIONS[mood]
    )
    genre_profile = GENRE_PROFILES[genre]
    length = float(bars * 4)
    chord_notes: list[dict[str, Any]] = []
    bass_notes: list[dict[str, Any]] = []
    melody_notes: list[dict[str, Any]] = []
    drum_notes: list[dict[str, Any]] = []
    chord_roots: list[str] = []
    previous_voicing: list[int] | None = None
    chord_count = int(length / harmonic_rhythm_beats)

    for chord_index in range(chord_count):
        degree = degrees[chord_index % len(degrees)]
        start = chord_index * harmonic_rhythm_beats
        raw_chord = _diatonic_chord(root_pc, scale, degree, CHORD_SIZES[chord_complexity])
        voicing = _smooth_voicing(raw_chord, previous_voicing)
        previous_voicing = voicing
        chord_roots.append(_pitch_name(raw_chord[0]))
        for tone_index, pitch in enumerate(voicing):
            chord_notes.append(
                note(pitch, start, harmonic_rhythm_beats * 0.95, 76 - tone_index * 2)
            )

        bass_root = raw_chord[0] - 12
        bass_step = float(genre_profile["bass_step"])
        position = 0.0
        while position < harmonic_rhythm_beats:
            approach = position + bass_step >= harmonic_rhythm_beats and chord_index + 1 < chord_count
            pitch = bass_root
            if approach and mood in {"chill", "dark", "bittersweet", "tense"}:
                next_degree = degrees[(chord_index + 1) % len(degrees)]
                next_root = 36 + root_pc + scale[next_degree]
                pitch = next_root - (1 if rng.random() < 0.5 else 2)
            bass_notes.append(
                note(pitch, start + position, bass_step * 0.82, 88 if position == 0 else 76)
            )
            position += bass_step

    eighth_count = int(length * 2)
    for step in range(eighth_count):
        if rng.random() > melody_density:
            continue
        time = step * 0.5
        chord_index = min(chord_count - 1, int(time / harmonic_rhythm_beats))
        degree = degrees[chord_index % len(degrees)]
        strong_beat = step % 2 == 0
        choices = [degree, (degree + 2) % 7, (degree + 4) % 7] if strong_beat else list(range(7))
        scale_degree = rng.choice(choices)
        pitch = 60 + root_pc + scale[scale_degree]
        if rng.random() < 0.18:
            pitch += 12
        start = _performed_time(time, step, swing, humanize, rng)
        velocity = 84 + (8 if strong_beat else 0) + _velocity_jitter(humanize, rng)
        melody_notes.append(note(pitch, start, 0.42, velocity, 0.94 if not strong_beat else 1.0))

    for bar in range(bars):
        bar_start = float(bar * 4)
        hat_step = float(genre_profile["hat_step"])
        hat_count = int(4.0 / hat_step)
        for step in range(hat_count):
            time = bar_start + step * hat_step
            start = _performed_time(time, step, swing, humanize, rng)
            base_velocity = 64 + (10 if step % 2 == 0 else 0)
            scaled_velocity = int(base_velocity * float(genre_profile["drum_velocity"]))
            drum_notes.append(
                note(
                    int(genre_profile["hat_pitch"]),
                    start,
                    min(0.12, hat_step * 0.45),
                    scaled_velocity + _velocity_jitter(humanize, rng),
                )
            )
        kick_steps = list(genre_profile["kick"])
        if mood == "dark" and genre not in {"edm", "hiphop"}:
            kick_steps = sorted(set(kick_steps + [1.75]))
        for position in kick_steps:
            velocity = int(103 * float(genre_profile["drum_velocity"]))
            drum_notes.append(
                note(36, bar_start + position, 0.2, velocity + _velocity_jitter(humanize, rng))
            )
        for position in genre_profile["snare"]:
            velocity = int(100 * float(genre_profile["drum_velocity"]))
            drum_notes.append(
                note(38, bar_start + float(position), 0.2, velocity + _velocity_jitter(humanize, rng))
            )

    return {
        "title": title.strip() or "My Song",
        "genre": genre,
        "mood": mood,
        "key": key,
        "mode": mode,
        "tempo": tempo,
        "bars": bars,
        "time_signature": "4/4",
        "chord_roots": chord_roots,
        "professional_settings": {
            "genre": genre,
            "mood": mood,
            "progression_degrees": [degree + 1 for degree in degrees],
            "chord_complexity": chord_complexity,
            "harmonic_rhythm_beats": harmonic_rhythm_beats,
            "melody_density": melody_density,
            "swing": swing,
            "humanize": humanize,
            "seed": seed,
        },
        "tracks": [
            {"name": "Chords", "role": "chords", "length_beats": length, "notes": chord_notes},
            {"name": "Bass", "role": "bass", "length_beats": length, "notes": bass_notes},
            {"name": "Melody", "role": "melody", "length_beats": length, "notes": melody_notes},
            {"name": "Drums", "role": "drums", "length_beats": length, "notes": drum_notes},
        ],
        "beginner_notes": [
            "各パートは別MIDIトラックなので、後から音色とノートを変更できます。",
            "DrumsはGeneral MIDIのKick 36、Snare 38、Closed Hi-Hat 42を使います。",
            "seedを変えると、同じ設定を保ったまま別のメロディ案を作れます。",
        ],
    }


def _validate_options(
    genre: str,
    mood: str,
    key: str,
    mode: str,
    tempo: float,
    bars: int,
    progression: list[int] | None,
    chord_complexity: str,
    harmonic_rhythm_beats: float,
    melody_density: float,
    swing: float,
    humanize: float,
) -> None:
    if key not in PITCH_CLASSES:
        raise ValueError("unsupported key")
    if mode not in SCALES:
        raise ValueError("mode must be 'major' or 'minor'")
    if genre not in GENRE_PROFILES:
        raise ValueError("genre must be pop, rock, edm, hiphop, rnb, jazz, or lofi")
    if mood not in MOOD_PROGRESSIONS:
        raise ValueError("mood must be bright, uplifting, chill, dark, bittersweet, or tense")
    if bars not in {4, 8, 16, 32}:
        raise ValueError("bars must be 4, 8, 16, or 32")
    if not 40 <= tempo <= 240:
        raise ValueError("tempo must be between 40 and 240")
    if progression is not None and (not progression or any(d < 1 or d > 7 for d in progression)):
        raise ValueError("progression degrees must be a non-empty list containing 1 through 7")
    if chord_complexity not in CHORD_SIZES:
        raise ValueError("chord_complexity must be triad, seventh, or ninth")
    if harmonic_rhythm_beats not in {1.0, 2.0, 4.0, 8.0}:
        raise ValueError("harmonic_rhythm_beats must be 1, 2, 4, or 8")
    if not 0.05 <= melody_density <= 1.0:
        raise ValueError("melody_density must be between 0.05 and 1.0")
    if not 0.0 <= swing <= 1.0 or not 0.0 <= humanize <= 1.0:
        raise ValueError("swing and humanize must be between 0.0 and 1.0")


def _diatonic_chord(root_pc: int, scale: list[int], degree: int, size: int) -> list[int]:
    pitches = []
    for chord_tone in range(size):
        scale_position = degree + chord_tone * 2
        octave = scale_position // 7
        scale_degree = scale_position % 7
        pitches.append(48 + root_pc + scale[scale_degree] + octave * 12)
    return pitches


def _smooth_voicing(chord: list[int], previous: list[int] | None) -> list[int]:
    candidates = []
    for inversion in range(len(chord)):
        inverted = chord[inversion:] + [pitch + 12 for pitch in chord[:inversion]]
        for octave_shift in (-12, 0, 12):
            candidate = [pitch + octave_shift for pitch in inverted]
            if min(candidate) >= 36 and max(candidate) <= 84:
                candidates.append(candidate)
    if not previous:
        return min(candidates, key=lambda candidate: abs(sum(candidate) / len(candidate) - 60))
    return min(
        candidates,
        key=lambda candidate: sum(abs(a - b) for a, b in zip(candidate, previous))
        + abs(sum(candidate) / len(candidate) - 60) * 0.1,
    )


def _performed_time(
    time: float, step: int, swing: float, humanize: float, rng: random.Random
) -> float:
    swing_offset = swing * 0.16 if step % 2 else 0.0
    jitter = rng.uniform(-0.025, 0.025) * humanize
    return max(0.0, time + swing_offset + jitter)


def _velocity_jitter(humanize: float, rng: random.Random) -> int:
    return int(round(rng.uniform(-9, 9) * humanize))


def _pitch_name(pitch: int) -> str:
    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return names[pitch % 12]
