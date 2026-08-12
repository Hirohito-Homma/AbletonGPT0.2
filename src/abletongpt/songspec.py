from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
import re
from typing import Any


@dataclass(frozen=True)
class SongTrackSpec:
    """A single track-level requirement inside a SongSpec."""

    name: str
    role: str
    length_beats: float
    note_count: int


@dataclass(frozen=True)
class SongSpec:
    """A compact, editable song-design record for KIHACHI MUSIC AI v0.1."""

    version: str
    title: str
    genre: str
    mood: str
    key: str
    mode: str
    tempo: float
    bars: int
    duration_seconds: float | None = None
    time_signature: str = "4/4"
    source: str = "compose"
    chord_roots: tuple[str, ...] = ()
    arrangement: tuple[str, ...] = ()
    tracks: tuple[SongTrackSpec, ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)


def build_song_spec_from_plan(plan: dict[str, Any]) -> SongSpec:
    """Convert a song-plan dict into the SongSpec used as the project's design core."""

    tracks = tuple(
        SongTrackSpec(
            name=str(track["name"]),
            role=str(track["role"]),
            length_beats=float(track["length_beats"]),
            note_count=len(track.get("notes", [])),
        )
        for track in plan.get("tracks", [])
    )
    return SongSpec(
        version="0.1",
        title=str(plan.get("title", "My Song")),
        genre=str(plan.get("genre", "pop")),
        mood=str(plan.get("mood", "bright")),
        key=str(plan.get("key", "C")),
        mode=str(plan.get("mode", "major")),
        tempo=float(plan.get("tempo", 120.0)),
        bars=int(plan.get("bars", 8)),
        duration_seconds=_duration_seconds_from_plan(plan),
        time_signature=str(plan.get("time_signature", "4/4")),
        chord_roots=tuple(str(root) for root in plan.get("chord_roots", [])),
        arrangement=tuple(str(section) for section in plan.get("arrangement", ())),
        tracks=tracks,
        settings=dict(plan.get("professional_settings", {})),
    )


def song_spec_to_dict(spec: SongSpec) -> dict[str, Any]:
    """Serialize a SongSpec to a JSON-ready dictionary."""

    return {
        "version": spec.version,
        "title": spec.title,
        "genre": spec.genre,
        "mood": spec.mood,
        "key": spec.key,
        "mode": spec.mode,
        "tempo": spec.tempo,
        "bars": spec.bars,
        "duration_seconds": spec.duration_seconds,
        "time_signature": spec.time_signature,
        "source": spec.source,
        "chord_roots": list(spec.chord_roots),
        "arrangement": list(spec.arrangement),
        "tracks": [
            {
                "name": track.name,
                "role": track.role,
                "length_beats": track.length_beats,
                "note_count": track.note_count,
            }
            for track in spec.tracks
        ],
        "settings": dict(spec.settings),
    }


def song_spec_to_yaml(spec: SongSpec) -> str:
    """Render a SongSpec as a small YAML document that is easy to hand-edit."""

    return _dump_yaml(song_spec_to_dict(spec))


def parse_song_spec_text(text: str) -> dict[str, Any]:
    """Parse SongSpec JSON or the project's small YAML subset into a dictionary."""

    source = str(text).strip()
    if not source:
        raise ValueError("song spec text is empty")
    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        payload, index = _parse_yaml_block(source.splitlines(), 0, 0)
        if _skip_blank_lines(source.splitlines(), index) != len(source.splitlines()):
            raise ValueError("could not parse the entire song spec text")
    else:
        if not isinstance(payload, dict):
            raise ValueError("song spec JSON must be an object")
    if not isinstance(payload, dict):
        raise ValueError("song spec text must describe an object")
    return payload


_GENRE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tech_house", ("tech house", "tech-house", "techhouse")),
    ("dub_techno", ("dub techno", "dub-techno", "dubtechno")),
    ("dub", ("dub",)),
    ("funk", ("funk", "mutation funk")),
    ("hiphop", ("hip hop", "hip-hop", "hiphop", "rap")),
    ("rnb", ("r&b", "rnb")),
    ("edm", ("edm", "dance")),
    ("lofi", ("lofi", "lo-fi")),
    ("jazz", ("jazz",)),
    ("rock", ("rock",)),
    ("pop", ("pop",)),
)

_MOOD_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("uplifting", ("uplifting", "bright", "明る", "高揚")),
    ("dark", ("dark", "darkness", "暗", "重", "陰")),
    ("chill", ("chill", "relaxed", "smooth", "落ち着", "ゆる")),
    ("bittersweet", ("bittersweet", "切な")),
    ("tense", ("tense", "紧", "緊張", "張り詰")),
)

_KEY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<root>[A-G](?:#|b)?)(?:\s*(?P<mode>major|minor|maj|min|m))?(?![A-Za-z])",
    re.IGNORECASE,
)
_BPM_PATTERN = re.compile(r"(?P<bpm>\d+(?:\.\d+)?)\s*bpm", re.IGNORECASE)
_BARS_PATTERN = re.compile(r"(?P<bars>\d+)\s*(?:bars?|小節)", re.IGNORECASE)
_MINUTES_PATTERN = re.compile(r"(?P<minutes>\d+(?:\.\d+)?)\s*(?:min|mins|minutes?|分)", re.IGNORECASE)


def build_song_spec_from_prompt(prompt: str, *, title: str | None = None) -> SongSpec:
    """Infer a first-pass SongSpec from a natural-language prompt."""

    text = " ".join(str(prompt).split())
    lowered = text.lower()
    genre = _infer_from_keywords(lowered, _GENRE_KEYWORDS, default="pop")
    mood = _infer_from_keywords(text, _MOOD_KEYWORDS, default="bright")
    key, mode = _infer_key_and_mode(text)
    tempo = _infer_tempo(text)
    duration_seconds = _infer_duration_seconds(text, tempo)
    bars = _infer_bars(text, tempo, duration_seconds)
    if title is None:
        title = _infer_title(text)
    plan = {
        "title": title,
        "genre": genre,
        "mood": mood,
        "key": key,
        "mode": mode,
        "tempo": tempo,
        "bars": bars,
        "time_signature": "4/4",
        "chord_roots": (),
        "arrangement": _default_arrangement_for_bars(bars),
        "tracks": [
            {"name": "Chords", "role": "chords", "length_beats": bars * 4.0, "notes": []},
            {"name": "Bass", "role": "bass", "length_beats": bars * 4.0, "notes": []},
            {"name": "Melody", "role": "melody", "length_beats": bars * 4.0, "notes": []},
            {"name": "Drums", "role": "drums", "length_beats": bars * 4.0, "notes": []},
        ],
        "professional_settings": {
            "genre": genre,
            "mood": mood,
            "progression_degrees": [],
            "chord_complexity": "triad",
            "harmonic_rhythm_beats": 4.0,
            "melody_density": 0.75,
            "swing": 0.0,
            "humanize": 0.0,
            "seed": 0,
        },
    }
    spec = build_song_spec_from_plan(plan)
    return SongSpec(
        version=spec.version,
        title=spec.title,
        genre=spec.genre,
        mood=spec.mood,
        key=spec.key,
        mode=spec.mode,
        tempo=spec.tempo,
        bars=spec.bars,
        duration_seconds=duration_seconds,
        time_signature=spec.time_signature,
        source="intent",
        chord_roots=spec.chord_roots,
        arrangement=spec.arrangement,
        tracks=spec.tracks,
        settings=spec.settings,
    )


def _duration_seconds_from_plan(plan: dict[str, Any]) -> float | None:
    duration = plan.get("duration_seconds")
    if duration is None:
        return None
    try:
        return float(duration)
    except (TypeError, ValueError):
        return None


def _infer_from_keywords(text: str, groups: tuple[tuple[str, tuple[str, ...]], ...], *, default: str) -> str:
    for label, keywords in groups:
        for keyword in keywords:
            if keyword in text:
                return label
    return default


def _infer_key_and_mode(text: str) -> tuple[str, str]:
    for match in _KEY_PATTERN.finditer(text):
        root = match.group("root").upper()
        mode_token = (match.group("mode") or "major").lower()
        mode = "minor" if mode_token in {"minor", "min", "m"} else "major"
        return root, mode
    return "C", "major"


def _infer_tempo(text: str) -> float:
    match = _BPM_PATTERN.search(text)
    if match:
        return float(match.group("bpm"))
    if "slow" in text.lower() or "ゆっくり" in text:
        return 96.0
    if "fast" in text.lower() or "速" in text:
        return 128.0
    return 110.0


def _infer_duration_seconds(text: str, tempo: float) -> float | None:
    match = _MINUTES_PATTERN.search(text)
    if match:
        return round(float(match.group("minutes")) * 60.0, 2)
    if "short" in text.lower() or "短" in text:
        return 120.0
    if "long" in text.lower() or "長" in text:
        return 360.0
    return None


def _infer_bars(text: str, tempo: float, duration_seconds: float | None) -> int:
    match = _BARS_PATTERN.search(text)
    if match:
        return max(4, int(match.group("bars")))
    if duration_seconds is not None:
        bars = round(duration_seconds * tempo / 240.0)
        return max(4, min(64, int(bars)))
    return 8


def _infer_title(text: str) -> str:
    title = text[:40].strip()
    return title or "Untitled Sketch"


def _default_arrangement_for_bars(bars: int) -> tuple[str, ...]:
    if bars <= 8:
        return ("intro", "groove", "drop", "outro")
    if bars <= 16:
        return ("intro", "groove_a", "build", "drop", "outro")
    return ("intro", "groove_a", "mutation", "breakdown", "drop", "groove_b", "outro")


def _parse_yaml_block(lines: list[str], start: int, indent: int) -> tuple[Any, int]:
    index = _skip_blank_lines(lines, start)
    if index >= len(lines):
        return [], index
    stripped = lines[index].lstrip(" ")
    if stripped.startswith("-"):
        return _parse_yaml_list(lines, index, indent)
    return _parse_yaml_mapping(lines, index, indent)


def _parse_yaml_mapping(lines: list[str], start: int, indent: int) -> tuple[dict[str, Any], int]:
    data: dict[str, Any] = {}
    index = start
    while True:
        index = _skip_blank_lines(lines, index)
        if index >= len(lines):
            break
        line = lines[index]
        current_indent = _line_indent(line)
        if current_indent < indent:
            break
        if current_indent != indent:
            raise ValueError("invalid indentation in song spec")
        stripped = line.strip()
        if stripped.startswith("-"):
            break
        key, separator, raw_value = stripped.partition(":")
        if not separator:
            raise ValueError("invalid mapping entry in song spec")
        value_text = raw_value.lstrip()
        index += 1
        if value_text:
            data[key] = _parse_yaml_scalar(value_text)
            continue
        next_index = _skip_blank_lines(lines, index)
        if next_index >= len(lines) or _line_indent(lines[next_index]) <= indent:
            data[key] = []
            index = next_index
            continue
        child_indent = _line_indent(lines[next_index])
        value, index = _parse_yaml_block(lines, next_index, child_indent)
        data[key] = value
    return data, index


def _parse_yaml_list(lines: list[str], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = start
    while True:
        index = _skip_blank_lines(lines, index)
        if index >= len(lines):
            break
        line = lines[index]
        current_indent = _line_indent(line)
        if current_indent < indent:
            break
        if current_indent != indent:
            raise ValueError("invalid list indentation in song spec")
        stripped = line.strip()
        if not stripped.startswith("-"):
            break
        item_text = stripped[1:].lstrip()
        index += 1
        if item_text:
            items.append(_parse_yaml_scalar(item_text))
            continue
        next_index = _skip_blank_lines(lines, index)
        if next_index >= len(lines) or _line_indent(lines[next_index]) <= indent:
            items.append(None)
            index = next_index
            continue
        child_indent = _line_indent(lines[next_index])
        value, index = _parse_yaml_block(lines, next_index, child_indent)
        items.append(value)
    return items, index


def _skip_blank_lines(lines: list[str], index: int) -> int:
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_yaml_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if value[:1] in {"'", '"'}:
        return ast.literal_eval(value)
    return value


def _dump_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_scalar(value)}"


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return repr(value) if value == "" or value.strip() != value or ":" in value else value
    return repr(value)