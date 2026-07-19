from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from typing import Any

from .composition import GENRE_PROFILES, MOOD_PROGRESSIONS, PITCH_CLASSES, SCALES, note
from .instruments import build_role_selection


PITCH_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
SOURCE_ROLES = {"auto", "chords", "bass", "melody", "pad", "drums"}
TARGET_ROLES = {"chords", "bass", "melody", "countermelody", "pad", "drums"}

_MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_COMMON_DRUM_PITCHES = {36, 38, 39, 42, 44, 46, 49, 51}


def analyze_midi_context(
    clip_data: dict[str, Any], source_role: str = "auto"
) -> dict[str, Any]:
    """Infer musical context from a Live MIDI clip response."""
    if source_role not in SOURCE_ROLES:
        raise ValueError("source_role must be auto, chords, bass, melody, pad, or drums")
    length = float(clip_data.get("length_beats", 0.0))
    if not 0.0 < length <= 4096.0:
        raise ValueError("source clip length must be between 0 and 4096 beats")
    notes = _normalized_notes(clip_data.get("notes", []), length)
    if not notes:
        raise ValueError("source MIDI clip contains no notes")
    inferred_role, role_metrics = _infer_role(notes)
    resolved_role = inferred_role if source_role == "auto" else source_role
    bars = max(length / 4.0, 0.25)
    pitches = [item["pitch"] for item in notes]
    durations = [item["duration"] for item in notes]
    velocities = [item["velocity"] for item in notes]

    key_result = None if resolved_role == "drums" else _infer_key(notes)
    harmonic_roots: list[int] = []
    if key_result:
        harmonic_roots = _infer_harmonic_roots(
            notes,
            length,
            int(key_result["tonic_pitch_class"]),
            str(key_result["mode"]),
        )

    warnings = []
    if clip_data.get("truncated"):
        warnings.append("ノート数が4096を超えたため、先頭4096ノートだけで解析しました。")
    if source_role != "auto" and source_role != inferred_role:
        warnings.append(
            "自動推定は%sですが、ユーザー指定の%sとして解析しました。"
            % (inferred_role, source_role)
        )
    if resolved_role == "drums":
        warnings.append("ドラムだけからキーは判定できません。和音系パートの生成にはキー指定が必要です。")

    return {
        "source": {
            "track_index": clip_data.get("track_index"),
            "track_name": clip_data.get("track", ""),
            "clip_index": clip_data.get("clip_index"),
            "clip_name": clip_data.get("clip", ""),
            "length_beats": length,
            "tempo": float(clip_data.get("tempo", 0.0)),
            "note_count": int(clip_data.get("note_count", len(notes))),
            "analyzed_note_count": len(notes),
            "fingerprint": _fingerprint(notes, length),
        },
        "musical_context": {
            "source_role": resolved_role,
            "auto_inferred_role": inferred_role,
            "role_confidence": role_metrics,
            "key": key_result,
            "pitch_range": {
                "lowest": min(pitches),
                "highest": max(pitches),
                "center": round(statistics.median(pitches), 2),
                "register": _register_name(statistics.median(pitches)),
            },
            "rhythm": {
                "estimated_grid_beats": _estimate_grid(notes),
                "notes_per_bar": round(len(notes) / bars, 2),
                "average_duration_beats": round(statistics.fmean(durations), 3),
            },
            "expression": {
                "average_velocity": round(statistics.fmean(velocities), 2),
                "velocity_range": [min(velocities), max(velocities)],
            },
            "polyphony": {
                "onset_polyphony_ratio": role_metrics["onset_polyphony_ratio"],
                "maximum_notes_at_same_onset": role_metrics["maximum_notes_at_same_onset"],
            },
            "harmonic_roots": [
                {"bar": index + 1, "pitch_class": root, "name": PITCH_NAMES[root]}
                for index, root in enumerate(harmonic_roots)
            ],
        },
        "warnings": warnings,
        "read_only": True,
    }


def build_complementary_track_plan(
    clip_data: dict[str, Any],
    target_role: str,
    source_role: str = "auto",
    genre: str = "pop",
    mood: str = "bright",
    key_override: str = "",
    mode_override: str = "",
    seed: int = 0,
    title: str = "",
) -> dict[str, Any]:
    if target_role not in TARGET_ROLES:
        raise ValueError(
            "target_role must be chords, bass, melody, countermelody, pad, or drums"
        )
    if genre not in GENRE_PROFILES:
        raise ValueError("unsupported genre")
    if mood not in MOOD_PROGRESSIONS:
        raise ValueError("unsupported mood")
    context = analyze_midi_context(clip_data, source_role)
    source_context = context["musical_context"]
    inferred_key = source_context["key"]
    if key_override:
        if key_override not in PITCH_CLASSES:
            raise ValueError("unsupported key_override")
        tonic = PITCH_CLASSES[key_override]
        key_name = key_override
    elif inferred_key:
        tonic = int(inferred_key["tonic_pitch_class"])
        key_name = str(inferred_key["tonic"])
    else:
        tonic = -1
        key_name = ""
    if mode_override:
        if mode_override not in SCALES:
            raise ValueError("mode_override must be major or minor")
        mode = mode_override
    elif inferred_key:
        mode = str(inferred_key["mode"])
    else:
        mode = ""
    if target_role != "drums" and (tonic < 0 or not mode):
        raise ValueError("key_override and mode_override are required for a drum-only source")

    length = float(clip_data["length_beats"])
    notes = _normalized_notes(clip_data["notes"], length)
    roots = [
        int(item["pitch_class"])
        for item in source_context.get("harmonic_roots", [])
    ]
    if not roots and tonic >= 0:
        roots = [tonic] * max(1, math.ceil(length / 4.0))
    rng = random.Random(seed)

    if target_role == "bass":
        generated = _generate_bass(roots, length, genre, rng)
    elif target_role in {"chords", "pad"}:
        generated = _generate_harmony(roots, tonic, mode, length, target_role)
    elif target_role in {"melody", "countermelody"}:
        generated = _generate_melody(
            roots, tonic, mode, length, notes, target_role == "countermelody", rng
        )
    else:
        generated = _generate_drums(length, genre, mood)

    track_name = title.strip() or {
        "chords": "AI Chords",
        "bass": "AI Bass",
        "melody": "AI Melody",
        "countermelody": "AI Counter Melody",
        "pad": "AI Pad",
        "drums": "AI Drums",
    }[target_role]
    instrument_role = "melody" if target_role == "countermelody" else target_role
    instrument = build_role_selection(instrument_role, genre, mood)
    collision_ratio = _onset_collision_ratio(notes, generated)
    return {
        "source_analysis": context,
        "generation": {
            "target_role": target_role,
            "genre": genre,
            "mood": mood,
            "key": "%s %s" % (key_name, mode) if key_name else None,
            "seed": seed,
            "source_fingerprint": context["source"]["fingerprint"],
            "strategy": _strategy_note(target_role),
            "source_onset_collision_ratio": round(collision_ratio, 3),
        },
        "target_track": {
            "name": track_name[:200],
            "role": target_role,
            "length_beats": length,
            "notes": generated,
            "note_count": len(generated),
        },
        "instrument_selection": instrument,
        "read_only": True,
        "next_step": "内容を確認後、create_complementary_midi_trackで新規MIDIトラックへ作成してください。",
    }


def _normalized_notes(raw_notes: list[dict[str, Any]], length: float) -> list[dict[str, Any]]:
    if not isinstance(raw_notes, list) or len(raw_notes) > 4096:
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


def _infer_role(notes: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    onset_groups: dict[float, list[dict[str, Any]]] = {}
    for item in notes:
        onset_groups.setdefault(round(item["start_time"], 3), []).append(item)
    group_sizes = [len(group) for group in onset_groups.values()]
    polyphonic_ratio = sum(size >= 2 for size in group_sizes) / len(group_sizes)
    common_drum_ratio = sum(item["pitch"] in _COMMON_DRUM_PITCHES for item in notes) / len(notes)
    median_pitch = statistics.median(item["pitch"] for item in notes)
    average_duration = statistics.fmean(item["duration"] for item in notes)
    if common_drum_ratio >= 0.72 and average_duration <= 0.75:
        role = "drums"
    elif polyphonic_ratio >= 0.35 and average_duration >= 1.5:
        role = "pad" if average_duration >= 3.0 else "chords"
    elif median_pitch < 52:
        role = "bass"
    else:
        role = "melody"
    return role, {
        "onset_polyphony_ratio": round(polyphonic_ratio, 3),
        "maximum_notes_at_same_onset": max(group_sizes),
        "common_drum_pitch_ratio": round(common_drum_ratio, 3),
    }


def _infer_key(notes: list[dict[str, Any]]) -> dict[str, Any]:
    histogram = [0.0] * 12
    for item in notes:
        weight = item["duration"] * (item["velocity"] / 127.0) * item["probability"]
        histogram[item["pitch"] % 12] += weight
    scores = []
    for mode, profile in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
        for tonic in range(12):
            rotated = [profile[(pitch_class - tonic) % 12] for pitch_class in range(12)]
            score = _cosine_similarity(histogram, rotated)
            scores.append((score, tonic, mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    confidence = max(0.0, min(1.0, (best[0] - second[0]) / max(abs(best[0]), 1e-9)))
    return {
        "tonic": PITCH_NAMES[best[1]],
        "tonic_pitch_class": best[1],
        "mode": best[2],
        "confidence": round(confidence, 3),
        "runner_up": "%s %s" % (PITCH_NAMES[second[1]], second[2]),
    }


def _infer_harmonic_roots(
    notes: list[dict[str, Any]], length: float, tonic: int, mode: str
) -> list[int]:
    scale = SCALES[mode]
    candidates = [(tonic + interval) % 12 for interval in scale]
    roots = []
    previous = tonic
    for bar_index in range(max(1, math.ceil(length / 4.0))):
        start = bar_index * 4.0
        end = min(length, start + 4.0)
        histogram = [0.0] * 12
        for item in notes:
            overlap = max(
                0.0,
                min(end, item["start_time"] + item["duration"])
                - max(start, item["start_time"]),
            )
            if overlap:
                histogram[item["pitch"] % 12] += overlap * item["velocity"] / 127.0
        if sum(histogram) == 0.0:
            roots.append(previous)
            continue
        scored = []
        for degree, root in enumerate(candidates):
            third = candidates[(degree + 2) % 7]
            fifth = candidates[(degree + 4) % 7]
            score = histogram[root] * 1.2 + histogram[third] + histogram[fifth]
            if root == previous:
                score += 0.05
            scored.append((score, root))
        previous = max(scored)[1]
        roots.append(previous)
    return roots


def _generate_bass(
    roots: list[int], length: float, genre: str, rng: random.Random
) -> list[dict[str, Any]]:
    result = []
    step = float(GENRE_PROFILES[genre]["bass_step"])
    for bar_index, root in enumerate(roots):
        bar_start = bar_index * 4.0
        position = 0.0
        pitch = 36 + root
        while pitch > 47:
            pitch -= 12
        while position < 4.0 and bar_start + position < length:
            current = pitch
            if position >= 3.0 and bar_index + 1 < len(roots) and rng.random() < 0.45:
                next_pitch = 36 + roots[bar_index + 1]
                while next_pitch > 47:
                    next_pitch -= 12
                current = next_pitch - (1 if rng.random() < 0.5 else 2)
            result.append(
                note(current, bar_start + position, min(step * 0.82, length - bar_start - position), 86)
            )
            position += step
    return result


def _generate_harmony(
    roots: list[int], tonic: int, mode: str, length: float, role: str
) -> list[dict[str, Any]]:
    result = []
    scale_pcs = [(tonic + interval) % 12 for interval in SCALES[mode]]
    for bar_index, root in enumerate(roots):
        start = bar_index * 4.0
        if start >= length:
            break
        degree = min(range(7), key=lambda index: _pitch_class_distance(scale_pcs[index], root))
        chord_pcs = [scale_pcs[degree], scale_pcs[(degree + 2) % 7], scale_pcs[(degree + 4) % 7]]
        pitches = []
        previous_pitch = 47
        for pitch_class in chord_pcs:
            pitch = 48 + pitch_class
            while pitch <= previous_pitch:
                pitch += 12
            pitches.append(pitch)
            previous_pitch = pitch
        duration = min(3.9 if role == "chords" else 4.0, length - start)
        velocity = 72 if role == "pad" else 78
        result.extend(note(pitch, start, duration, velocity - index * 2) for index, pitch in enumerate(pitches))
    return result


def _generate_melody(
    roots: list[int],
    tonic: int,
    mode: str,
    length: float,
    source_notes: list[dict[str, Any]],
    counter: bool,
    rng: random.Random,
) -> list[dict[str, Any]]:
    result = []
    scale_pcs = [(tonic + interval) % 12 for interval in SCALES[mode]]
    source_onsets = [item["start_time"] for item in source_notes]
    step_count = math.ceil(length / 0.5)
    for step in range(step_count):
        start = step * 0.5
        if start >= length:
            break
        near_source = any(abs(onset - start) < 0.16 for onset in source_onsets)
        if counter and (near_source or step % 2 == 0):
            continue
        if not counter and rng.random() > 0.68:
            continue
        root = roots[min(len(roots) - 1, int(start // 4.0))]
        root_degree = min(
            range(7), key=lambda index: _pitch_class_distance(scale_pcs[index], root)
        )
        choices = [root_degree, (root_degree + 2) % 7, (root_degree + 4) % 7]
        degree = rng.choice(choices if step % 2 == 0 else list(range(7)))
        pitch = 60 + scale_pcs[degree]
        if counter:
            pitch += 12 if pitch < 67 else 0
        active_source = [
            item["pitch"]
            for item in source_notes
            if item["start_time"] <= start < item["start_time"] + item["duration"]
        ]
        if active_source and min(abs(pitch - source_pitch) for source_pitch in active_source) <= 2:
            pitch = pitch + 12 if pitch <= 72 else pitch - 12
        result.append(note(pitch, start, min(0.42, length - start), 82 if counter else 88))
    if not result:
        result.append(note(60 + tonic, 0.5 if length > 1.0 else 0.0, min(0.5, length), 82))
    return result


def _generate_drums(length: float, genre: str, mood: str) -> list[dict[str, Any]]:
    result = []
    profile = GENRE_PROFILES[genre]
    for bar_index in range(math.ceil(length / 4.0)):
        start = bar_index * 4.0
        hat_step = float(profile["hat_step"])
        position = 0.0
        hat_index = 0
        while position < 4.0 and start + position < length:
            velocity = int((66 + (9 if hat_index % 2 == 0 else 0)) * float(profile["drum_velocity"]))
            result.append(note(int(profile["hat_pitch"]), start + position, 0.1, velocity))
            position += hat_step
            hat_index += 1
        kick_positions = list(profile["kick"])
        if mood == "dark" and genre not in {"edm", "hiphop"}:
            kick_positions.append(1.75)
        for position in sorted(set(kick_positions)):
            if start + position < length:
                result.append(note(36, start + position, 0.2, 104))
        for position in profile["snare"]:
            if start + float(position) < length:
                result.append(note(38, start + float(position), 0.2, 100))
    return result


def _estimate_grid(notes: list[dict[str, Any]]) -> float:
    onsets = [item["start_time"] for item in notes]
    for grid in (2.0, 1.0, 0.5, 0.25, 0.125):
        aligned = sum(abs(onset / grid - round(onset / grid)) <= 0.06 for onset in onsets)
        if aligned / len(onsets) >= 0.85:
            return grid
    return 0.0625


def _onset_collision_ratio(
    source_notes: list[dict[str, Any]], generated_notes: list[dict[str, Any]]
) -> float:
    if not generated_notes:
        return 0.0
    source = {round(item["start_time"], 2) for item in source_notes}
    collisions = sum(round(item["start_time"], 2) in source for item in generated_notes)
    return collisions / len(generated_notes)


def _fingerprint(notes: list[dict[str, Any]], length: float) -> str:
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


def _cosine_similarity(first: list[float], second: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(first, second))
    denominator = math.sqrt(sum(value * value for value in first)) * math.sqrt(
        sum(value * value for value in second)
    )
    return numerator / denominator if denominator else 0.0


def _pitch_class_distance(first: int, second: int) -> int:
    distance = abs(first - second) % 12
    return min(distance, 12 - distance)


def _register_name(center: float) -> str:
    if center < 48:
        return "low"
    if center < 60:
        return "low_mid"
    if center < 72:
        return "mid"
    return "high"


def _strategy_note(role: str) -> str:
    return {
        "bass": "小節ごとの推定ルートを低音域へ配置し、ジャンルのベース密度を反映します。",
        "chords": "推定ハーモニーをダイアトニック三和音へ整え、4拍単位で配置します。",
        "pad": "推定ハーモニーを長い三和音として配置し、元パートの後ろを支えます。",
        "melody": "推定スケールとコードトーンを使い、元クリップと近接する音を避けます。",
        "countermelody": "元ノートの空いているオフビートを優先し、音域衝突を避けます。",
        "drums": "元クリップと同じ長さで、指定ジャンルとムードのドラムグルーヴを作ります。",
    }[role]
