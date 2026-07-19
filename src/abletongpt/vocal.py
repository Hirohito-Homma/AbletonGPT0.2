from __future__ import annotations

import re
from typing import Any

from .composition import build_song_plan


def build_vocal_plan(
    title: str,
    lyrics: str,
    genre: str,
    mood: str,
    key: str,
    mode: str,
    tempo: float,
    bars: int,
    seed: int,
    melody_density: float = 0.7,
) -> dict[str, Any]:
    syllables = _lyric_units(lyrics)
    if not syllables:
        raise ValueError("lyrics must not be empty")
    song = build_song_plan(
        title,
        genre,
        mood,
        key,
        mode,
        tempo,
        bars,
        melody_density=melody_density,
        seed=seed,
    )
    melody = next(track for track in song["tracks"] if track["role"] == "melody")
    events = []
    for index, midi_note in enumerate(melody["notes"]):
        events.append(
            {
                "lyric": syllables[index % len(syllables)],
                "pitch": midi_note["pitch"],
                "start_time": midi_note["start_time"],
                "duration": midi_note["duration"],
                "velocity": midi_note["velocity"],
            }
        )
    return {
        "title": song["title"],
        "lyrics": lyrics.strip(),
        "language_hint": _language_hint(lyrics),
        "tempo": tempo,
        "key": "%s %s" % (key, mode),
        "bars": bars,
        "seed": seed,
        "midi_notes": melody["notes"],
        "vocal_events": events,
        "render_contract": {
            "preferred_format": "WAV",
            "sample_rate": 48000,
            "bit_depth": 24,
            "dry_vocal": True,
            "tempo_sync_required": True,
            "start_at_bar_one": True,
        },
    }


def _lyric_units(lyrics: str) -> list[str]:
    normalized = re.sub(r"[\r\n]+", " ", lyrics.strip())
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", normalized):
        return [char for char in normalized if not char.isspace() and char not in "、。！？,.!?「」『』"]
    return [unit for unit in re.split(r"\s+", normalized) if unit]


def _language_hint(lyrics: str) -> str:
    if re.search(r"[\u3040-\u30ff]", lyrics):
        return "ja"
    if re.search(r"[\u3400-\u9fff]", lyrics):
        return "cjk"
    return "en"
