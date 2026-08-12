from __future__ import annotations

import json
import sys
import types
import wave
from pathlib import Path

from abletongpt.cli.ui import _dispatch, render_index
from abletongpt.songspec import build_song_spec_from_prompt, song_spec_to_yaml


def _write_tone_wav(path: Path, seconds: float = 1.0, sample_rate: int = 48000) -> Path:
    import math
    import struct

    frames = bytearray()
    for i in range(int(sample_rate * seconds)):
        value = int(0.1 * 32767 * math.sin(2 * math.pi * 1000 * i / sample_rate))
        frames.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
    return path


def test_render_index_contains_the_main_panels():
    html = render_index()
    assert "AbletonGPT Studio" in html
    assert "Intent -> SongSpec" in html
    assert "Audio / Loudness" in html
    assert "Live" in html
    assert "Create In Live" in html


def test_dispatch_intent_returns_song_spec_and_text():
    payload = _dispatch(
        "intent",
        {"prompt": "110 BPM, D# minor, dub techno", "title": "Demo", "output": "json"},
    )

    assert payload["read_only"] is True
    assert payload["song_spec"]["title"] == "Demo"
    assert payload["text"].startswith("{")


def test_dispatch_compose_includes_song_spec():
    payload = _dispatch(
        "compose",
        {
            "title": "Demo",
            "genre": "edm",
            "mood": "bright",
            "key": "C",
            "mode": "major",
            "tempo": 120,
            "bars": 8,
            "seed": 7,
        },
    )

    assert payload["title"] == "Demo"
    assert payload["song_spec"]["version"] == "0.1"


def test_dispatch_compose_from_song_spec_yaml():
    spec = build_song_spec_from_prompt("110 BPM, D# minor, dub techno", title="Demo")

    payload = _dispatch("compose-from-spec", {"song_spec": song_spec_to_yaml(spec)})

    assert payload["title"] == "Demo"
    assert payload["genre"] == "dub_techno"
    assert payload["song_spec_source"]["genre"] == "dub_techno"


def test_dispatch_audio_loudness_uses_the_file_path(tmp_path: Path):
    wav = _write_tone_wav(tmp_path / "tone.wav")

    payload = _dispatch("audio-loudness", {"file_path": str(wav), "target_lufs": -14})

    assert payload["file"]["name"] == "tone.wav"
    assert payload["analysis"]["target_lufs"] == -14


def test_dispatch_live_status_uses_server_api(monkeypatch):
    fake_server = types.SimpleNamespace(
        get_live_state=lambda: {"tempo": 110, "is_playing": False},
        get_mix_snapshot=lambda: {"master": {"volume": 0.85}},
    )
    monkeypatch.setitem(sys.modules, "abletongpt.server", fake_server)

    payload = _dispatch("live", {"live_action": "status"})

    assert payload["state"]["tempo"] == 110
    assert payload["mix"]["master"]["volume"] == 0.85


def test_dispatch_live_from_song_spec_uses_server_api(monkeypatch):
    calls: list[dict[str, object]] = []

    def create_song_sketch(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "title": kwargs["title"], "genre": kwargs["genre"]}

    fake_server = types.SimpleNamespace(create_song_sketch=create_song_sketch)
    monkeypatch.setitem(sys.modules, "abletongpt.server", fake_server)

    spec = build_song_spec_from_prompt("110 BPM, D# minor, dub techno", title="Demo")
    payload = _dispatch("live-from-spec", {"song_spec": song_spec_to_yaml(spec)})

    assert payload["ok"] is True
    assert payload["title"] == "Demo"
    assert payload["song_spec_source"]["genre"] == "dub_techno"
    assert calls[0]["genre"] == "dub_techno"


def test_dispatch_live_from_song_spec_auto_apply_and_play(monkeypatch):
    calls: dict[str, object] = {
        "create": [],
        "insert": [],
        "drum": [],
        "scene": [],
        "transport": [],
    }

    def create_song_sketch(**kwargs):
        calls["create"].append(kwargs)
        return {
            "title": kwargs["title"],
            "created": [
                {"track_index": 10, "track": "Chords"},
                {"track_index": 11, "track": "Bass"},
                {"track_index": 12, "track": "Melody"},
                {"track_index": 13, "track": "Drums"},
            ],
        }

    def apply_live_instrument_selection(**kwargs):
        calls["insert"].append(kwargs)
        return {"applied": {"ok": True}}

    def apply_live_drum_kit(**kwargs):
        calls["drum"].append(kwargs)
        return {"applied": {"ok": True}}

    def get_track_devices(track_index):
        return {"track_index": track_index, "devices": [{"name": "Verified Device"}]}

    def fire_scene(scene_index):
        calls["scene"].append(scene_index)
        return {"ok": True, "scene_index": scene_index}

    def set_transport(action):
        calls["transport"].append(action)
        return {"ok": True, "action": action}

    fake_server = types.SimpleNamespace(
        create_song_sketch=create_song_sketch,
        apply_live_instrument_selection=apply_live_instrument_selection,
        apply_live_drum_kit=apply_live_drum_kit,
        get_track_devices=get_track_devices,
        fire_scene=fire_scene,
        set_transport=set_transport,
    )
    monkeypatch.setitem(sys.modules, "abletongpt.server", fake_server)

    spec = build_song_spec_from_prompt("110 BPM, D# minor, dub techno", title="Demo")
    payload = _dispatch(
        "live-from-spec",
        {
            "song_spec": song_spec_to_yaml(spec),
            "auto_apply_instruments": True,
            "auto_fire_scene": True,
            "auto_play": True,
            "scene_index": 0,
        },
    )

    assert payload["title"] == "Demo"
    assert len(payload["auto_apply_instruments"]) == 4
    assert all(entry["ok"] for entry in payload["auto_apply_instruments"])
    assert len(calls["insert"]) == 3
    assert len(calls["drum"]) == 1
    assert all(entry["devices"] for entry in payload["auto_apply_instruments"])
    assert calls["scene"] == [0]
    assert calls["transport"] == ["play"]