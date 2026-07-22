import json
import math
import os
import struct
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch

from abletongpt.bridge import AbletonBridge, BridgeConfig


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.sent = b""
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, payload):
        self.sent += payload

    def recv(self, _size):
        response, self.response = self.response, b""
        return response


def call_with_fake_response(command, response, **params):
    connection = FakeConnection((json.dumps({"ok": True, "result": response}) + "\n").encode())
    bridge = AbletonBridge(BridgeConfig(timeout=1))
    with patch("abletongpt.bridge.socket.create_connection", return_value=connection):
        result = bridge.call(command, **params)
    return result, json.loads(connection.sent.decode())


def test_bridge_round_trip():
    result, request = call_with_fake_response("set_tempo", {"tempo": 128}, bpm=128)
    assert request["command"] == "set_tempo"
    assert request["params"] == {"bpm": 128}
    assert result == {"tempo": 128}


def test_bridge_request_timeout_is_local_only():
    connection = FakeConnection(
        (json.dumps({"ok": True, "result": {"loaded": "Kit"}}) + "\n").encode()
    )
    bridge = AbletonBridge(BridgeConfig(timeout=1))
    with patch(
        "abletongpt.bridge.socket.create_connection", return_value=connection
    ) as create_connection:
        bridge.call("load_preset", _timeout=30.0, track_index=1, name="Kit")

    create_connection.assert_called_once_with(("127.0.0.1", 9877), 30.0)
    assert connection.timeout == 30.0
    request = json.loads(connection.sent.decode())
    assert request["params"] == {"track_index": 1, "name": "Kit"}


def test_create_track_request():
    response = {"index": 2, "name": "Bass", "track_type": "midi", "total_tracks": 3}
    result, request = call_with_fake_response(
        "create_track", response, track_type="midi", name="Bass", index=-1
    )
    assert request["params"] == {"track_type": "midi", "name": "Bass", "index": -1}
    assert result["name"] == "Bass"


def test_set_normalized_device_parameter_request():
    response = {
        "device": "Auto Filter",
        "parameter": {"index": 2, "normalized_value": 0.35},
    }
    result, request = call_with_fake_response(
        "set_device_parameter",
        response,
        track_index=1,
        device_index=0,
        parameter_index=2,
        value=0.35,
        normalized=True,
    )
    assert request["params"] == {
        "track_index": 1,
        "device_index": 0,
        "parameter_index": 2,
        "value": 0.35,
        "normalized": True,
    }
    assert result["parameter"]["normalized_value"] == 0.35


def test_add_native_device_request():
    response = {
        "track": "Vocal",
        "index": 1,
        "name": "EQ Eight",
        "class_display_name": "EQ Eight",
        "type": 2,
        "device_count": 2,
    }
    result, request = call_with_fake_response(
        "add_native_device",
        response,
        track_index=0,
        device_name="EQ Eight",
        index=-1,
    )
    assert request["params"] == {
        "track_index": 0,
        "device_name": "EQ Eight",
        "index": -1,
    }
    assert result["name"] == "EQ Eight"


def test_insert_first_available_instrument_request():
    response = {
        "track": "Bass",
        "track_index": 1,
        "index": 0,
        "name": "Drift",
        "requested_candidate": "Drift",
        "fallback_used": True,
        "attempted": ["Operator", "Drift"],
        "failed_candidates": [{"name": "Operator", "error": "not available"}],
        "device_count": 1,
    }
    result, request = call_with_fake_response(
        "insert_first_available_instrument",
        response,
        track_index=1,
        candidates=["Operator", "Drift"],
        index=-1,
    )
    assert request["params"] == {
        "track_index": 1,
        "candidates": ["Operator", "Drift"],
        "index": -1,
    }
    assert result["name"] == "Drift"
    assert result["fallback_used"] is True


def test_create_midi_clip_request():
    notes = [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 90}]
    response = {
        "track": "Melody",
        "clip_index": 0,
        "clip": "Idea - Melody",
        "length_beats": 16.0,
        "note_count": 1,
    }
    result, request = call_with_fake_response(
        "create_midi_clip",
        response,
        track_index=2,
        clip_index=0,
        name="Idea - Melody",
        length_beats=16.0,
        notes=notes,
    )
    assert request["params"]["notes"] == notes
    assert result["note_count"] == 1


def test_get_midi_clip_notes_request():
    response = {
        "track_index": 0,
        "track": "User Chords",
        "clip_index": 1,
        "clip": "Verse",
        "length_beats": 16.0,
        "tempo": 110.0,
        "notes": [{"pitch": 60, "start_time": 0.0, "duration": 4.0, "velocity": 90}],
        "note_count": 1,
        "truncated": False,
    }
    result, request = call_with_fake_response(
        "get_midi_clip_notes", response, track_index=0, clip_index=1
    )
    assert request["params"] == {"track_index": 0, "clip_index": 1}
    assert result["clip"] == "Verse"
    assert result["notes"][0]["pitch"] == 60


def test_get_audio_clip_paths_request():
    response = {
        "track_index": 7,
        "track": "8-test002",
        "view": "both",
        "clips": [
            {
                "location": "arrangement",
                "index": 0,
                "name": "test002",
                "file_path": "/audio/test002.wav",
                "warping": True,
                "looping": False,
                "length_beats": 128.0,
                "sample_length": 1000,
                "sample_rate": 48000.0,
                "gain_display": "0.0 dB",
                "start_time": 0.0,
                "end_time": 128.0,
            }
        ],
        "clip_count": 1,
        "truncated": False,
        "read_only": True,
    }
    result, request = call_with_fake_response(
        "get_audio_clip_paths", response, track_index=7, view="both"
    )
    assert request["params"] == {"track_index": 7, "view": "both"}
    assert result["clips"][0]["file_path"] == "/audio/test002.wav"
    assert result["read_only"] is True


def test_song_plan_is_editable_and_bounded():
    from abletongpt.composition import build_song_plan

    plan = build_song_plan("First Song", "pop", "bright", "C", "major", 110, 8)
    assert [track["role"] for track in plan["tracks"]] == [
        "chords",
        "bass",
        "melody",
        "drums",
    ]
    assert all(track["length_beats"] == 32.0 for track in plan["tracks"])
    assert all(
        0 <= midi_note["pitch"] <= 127
        for track in plan["tracks"]
        for midi_note in track["notes"]
    )


def test_pro_plan_is_reproducible_and_configurable():
    from abletongpt.composition import build_song_plan

    options = {
        "progression": [2, 5, 1, 6],
        "chord_complexity": "seventh",
        "harmonic_rhythm_beats": 2.0,
        "melody_density": 0.55,
        "swing": 0.4,
        "humanize": 0.3,
        "seed": 42,
    }
    first = build_song_plan("Pro", "rnb", "chill", "D", "minor", 92, 8, **options)
    second = build_song_plan("Pro", "rnb", "chill", "D", "minor", 92, 8, **options)
    assert first == second
    assert first["professional_settings"]["progression_degrees"] == [2, 5, 1, 6]
    assert len(first["tracks"][0]["notes"]) == 64


def test_seed_changes_melody_without_changing_harmony():
    from abletongpt.composition import build_song_plan

    first = build_song_plan("A", "pop", "bright", "C", "major", 120, 8, seed=1)
    second = build_song_plan("A", "pop", "bright", "C", "major", 120, 8, seed=2)
    assert first["tracks"][0]["notes"] == second["tracks"][0]["notes"]
    assert first["tracks"][2]["notes"] != second["tracks"][2]["notes"]


def test_vocal_plan_maps_lyrics_to_notes():
    from abletongpt.vocal import build_vocal_plan

    plan = build_vocal_plan(
        "Vocal", "あ し た へ", "pop", "uplifting", "C", "major", 110, 4, 7
    )
    assert plan["language_hint"] == "ja"
    assert len(plan["vocal_events"]) == len(plan["midi_notes"])
    assert {event["lyric"] for event in plan["vocal_events"]} <= {"あ", "し", "た", "へ"}


def test_import_audio_clip_request():
    response = {
        "track": "AI Vocal",
        "clip_index": 0,
        "clip": "Lead Take",
        "file_path": "/tmp/vocal.wav",
        "length": 32.0,
    }
    result, request = call_with_fake_response(
        "import_audio_clip",
        response,
        track_index=4,
        clip_index=0,
        file_path="/tmp/vocal.wav",
        name="Lead Take",
    )
    assert request["params"]["file_path"] == "/tmp/vocal.wav"
    assert result["clip"] == "Lead Take"


def test_mix_control_request():
    result, request = call_with_fake_response(
        "set_track_pan", {"track": "Guitar", "pan": -0.25}, track_index=1, pan=-0.25
    )
    assert request["params"] == {"track_index": 1, "pan": -0.25}
    assert result["pan"] == -0.25


def test_stop_track_clips_request():
    result, request = call_with_fake_response(
        "stop_track_clips", {"track": "Chords", "stopped": True}, track_index=0
    )
    assert request["params"] == {"track_index": 0}
    assert result["stopped"] is True


def test_fire_clip_group_request():
    response = {
        "clip_index": 2,
        "launch_mode": "single_command_quantized_group",
        "fired": [
            {"track_index": 0, "track": "Melody", "clip": "Chorus Melody"},
            {"track_index": 1, "track": "Chords", "clip": "Chorus Chords"},
        ],
    }
    result, request = call_with_fake_response(
        "fire_clip_group", response, track_indices=[0, 1], clip_index=2
    )
    assert request["params"] == {"track_indices": [0, 1], "clip_index": 2}
    assert result["launch_mode"] == "single_command_quantized_group"
    assert [item["track_index"] for item in result["fired"]] == [0, 1]


def test_duplicate_clip_to_slot_request():
    response = {
        "track_index": 5,
        "track": "Clap Loop",
        "source_clip_index": 0,
        "destination_clip_index": 1,
        "clip": "B Section - Clap Loop",
        "is_audio_clip": True,
        "is_midi_clip": False,
    }
    result, request = call_with_fake_response(
        "duplicate_clip_to_slot",
        response,
        track_index=5,
        source_clip_index=0,
        destination_clip_index=1,
        name="B Section - Clap Loop",
    )
    assert request["params"] == {
        "track_index": 5,
        "source_clip_index": 0,
        "destination_clip_index": 1,
        "name": "B Section - Clap Loop",
    }
    assert result["is_audio_clip"] is True


def test_fire_scene_request():
    response = {
        "scene_index": 2,
        "scene": "3",
        "launch_mode": "single_scene_fire",
        "fired": [
            {"track_index": 0, "track": "Melody", "clip": "Chorus Melody"},
            {"track_index": 5, "track": "Clap Loop", "clip": "Chorus Clap"},
        ],
    }
    result, request = call_with_fake_response("fire_scene", response, scene_index=2)
    assert request["params"] == {"scene_index": 2}
    assert result["launch_mode"] == "single_scene_fire"
    assert len(result["fired"]) == 2


def test_copy_session_clip_to_arrangement_request():
    response = {
        "track_index": 0,
        "track": "Melody",
        "source_clip_index": 2,
        "source_clip": "Chorus Melody",
        "arrangement_clip": "Chorus Melody",
        "start_time": 64.0,
        "end_time": 96.0,
        "is_audio_clip": False,
        "is_midi_clip": True,
    }
    result, request = call_with_fake_response(
        "copy_session_clip_to_arrangement",
        response,
        track_index=0,
        clip_index=2,
        destination_time_beats=64.0,
        name="",
    )
    assert request["params"] == {
        "track_index": 0,
        "clip_index": 2,
        "destination_time_beats": 64.0,
        "name": "",
    }
    assert result["start_time"] == 64.0


def test_copy_scene_to_arrangement_request():
    response = {
        "scene_index": 2,
        "scene": "Chorus",
        "destination_time_beats": 64.0,
        "copied": [
            {
                "track_index": 0,
                "track": "Melody",
                "source_clip": "Chorus Melody",
                "arrangement_clip": "Chorus Melody",
                "start_time": 64.0,
                "end_time": 96.0,
                "is_audio_clip": False,
                "is_midi_clip": True,
            }
        ],
        "skipped_empty_tracks": [],
        "collision_policy": "reject_before_copy",
    }
    result, request = call_with_fake_response(
        "copy_scene_to_arrangement",
        response,
        scene_index=2,
        destination_time_beats=64.0,
        track_indices=None,
    )
    assert request["params"] == {
        "scene_index": 2,
        "destination_time_beats": 64.0,
        "track_indices": None,
    }
    assert result["collision_policy"] == "reject_before_copy"


def test_bridge_config_reads_shared_file_and_environment_override():
    from abletongpt.bridge import BridgeConfig

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        path.write_text(
            json.dumps({"host": "127.0.0.1", "port": 9999, "token": "shared", "timeout": 5}),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"ABLETONGPT_CONFIG": str(path), "ABLETONGPT_PORT": "9988"},
            clear=False,
        ):
            config = BridgeConfig.load()
        assert config.port == 9988
        assert config.token == "shared"
        assert config.timeout == 5


def test_genre_and_mood_are_independent_dimensions():
    from abletongpt.composition import build_song_plan

    pop = build_song_plan("A", "pop", "bright", "C", "major", 120, 8, seed=3)
    edm = build_song_plan("A", "edm", "bright", "C", "major", 120, 8, seed=3)
    dark = build_song_plan("A", "pop", "dark", "C", "major", 120, 8, seed=3)

    assert pop["tracks"][0]["notes"] == edm["tracks"][0]["notes"]
    assert pop["tracks"][3]["notes"] != edm["tracks"][3]["notes"]
    assert pop["tracks"][0]["notes"] != dark["tracks"][0]["notes"]
    assert pop["genre"] == "pop"
    assert pop["mood"] == "bright"


def test_ai_instrument_plan_uses_role_genre_mood_and_edition():
    from abletongpt.instruments import build_instrument_plan

    suite = build_instrument_plan("edm", "dark", ["bass", "drums"], "suite")
    standard = build_instrument_plan("pop", "bright", ["chords"], "standard")

    assert suite["selections"][0]["selected_instrument"] == "Operator"
    assert suite["selections"][1]["selected_instrument"] == "Drum Rack"
    assert suite["selections"][1]["requires_content"] is True
    assert standard["selections"][0]["selected_instrument"] == "Drift"
    assert suite["apply_contract"]["requires_confirmation"] is True


def test_user_preferred_instrument_stays_allowlisted_and_role_compatible():
    from abletongpt.instruments import build_role_selection

    selection = build_role_selection(
        "melody", "jazz", "chill", "unknown", preferred_instrument="Collision"
    )
    assert selection["selected_instrument"] == "Collision"
    assert selection["candidates"][0] == "Collision"

    try:
        build_role_selection("drums", "pop", "bright", preferred_instrument="Operator")
    except ValueError as exc:
        assert "does not support" in str(exc)
    else:
        raise AssertionError("role-incompatible preferred instrument must be rejected")


def _user_chord_clip():
    notes = []
    for start, pitches in (
        (0.0, [60, 64, 67]),
        (4.0, [65, 69, 72]),
        (8.0, [67, 71, 74]),
        (12.0, [60, 64, 67]),
    ):
        for pitch in pitches:
            notes.append(
                {
                    "pitch": pitch,
                    "start_time": start,
                    "duration": 3.8,
                    "velocity": 90,
                    "probability": 1.0,
                }
            )
    return {
        "track_index": 0,
        "track": "User Chords",
        "clip_index": 0,
        "clip": "Verse",
        "length_beats": 16.0,
        "tempo": 110.0,
        "notes": notes,
        "note_count": len(notes),
        "truncated": False,
    }


def test_existing_midi_clip_analysis_finds_role_key_and_harmony():
    from abletongpt.contextual import analyze_midi_context

    result = analyze_midi_context(_user_chord_clip())
    context = result["musical_context"]
    assert context["source_role"] == "pad"
    assert context["key"]["tonic"] == "C"
    assert context["key"]["mode"] == "major"
    assert [item["name"] for item in context["harmonic_roots"]] == ["C", "F", "G", "C"]
    assert result["source"]["fingerprint"]
    assert result["read_only"] is True


def test_complementary_countermelody_is_deterministic_and_avoids_source_onsets():
    from abletongpt.contextual import build_complementary_track_plan

    first = build_complementary_track_plan(
        _user_chord_clip(), "countermelody", genre="pop", mood="uplifting", seed=7
    )
    second = build_complementary_track_plan(
        _user_chord_clip(), "countermelody", genre="pop", mood="uplifting", seed=7
    )
    assert first == second
    assert first["target_track"]["notes"]
    assert first["generation"]["key"] == "C major"
    assert first["generation"]["source_onset_collision_ratio"] == 0.0
    assert first["instrument_selection"]["selected_instrument"] == "Wavetable"


def test_drum_only_source_requires_key_for_harmonic_complement():
    from abletongpt.contextual import build_complementary_track_plan

    drum_clip = {
        "track_index": 0,
        "track": "User Drums",
        "clip_index": 0,
        "clip": "Beat",
        "length_beats": 4.0,
        "tempo": 100.0,
        "notes": [
            {"pitch": 36, "start_time": 0.0, "duration": 0.2, "velocity": 100},
            {"pitch": 38, "start_time": 1.0, "duration": 0.2, "velocity": 100},
            {"pitch": 42, "start_time": 2.0, "duration": 0.1, "velocity": 80},
            {"pitch": 38, "start_time": 3.0, "duration": 0.2, "velocity": 100},
        ],
        "note_count": 4,
        "truncated": False,
    }
    try:
        build_complementary_track_plan(drum_clip, "bass")
    except ValueError as exc:
        assert "key_override" in str(exc)
    else:
        raise AssertionError("harmonic generation from drums must require an explicit key")

    plan = build_complementary_track_plan(
        drum_clip, "bass", key_override="D", mode_override="minor"
    )
    assert plan["generation"]["key"] == "D minor"
    assert plan["target_track"]["notes"]


def test_confirmed_complementary_plan_creates_a_new_track_without_touching_source():
    from abletongpt import server
    from abletongpt.contextual import build_complementary_track_plan

    source = _user_chord_clip()
    reviewed = build_complementary_track_plan(source, "bass", seed=4)
    calls = []

    def fake_call(command, **params):
        calls.append((command, params))
        if command == "get_midi_clip_notes":
            return source
        if command == "get_state":
            return {"scene_count": 2, "tracks": [{"name": "User Chords"}]}
        if command == "create_track":
            return {"index": 1, "name": params["name"], "track_type": "midi"}
        if command == "create_midi_clip":
            return {"track": "AI Bass", "clip_index": 0, "clip": params["name"]}
        raise AssertionError("unexpected command: %s" % command)

    with patch.object(server.bridge, "call", side_effect=fake_call):
        result = server.create_complementary_midi_track(
            0,
            0,
            "bass",
            seed=4,
            expected_source_fingerprint=reviewed["generation"]["source_fingerprint"],
        )

    assert result["track_index"] == 1
    assert [command for command, _params in calls] == [
        "get_midi_clip_notes",
        "get_state",
        "create_track",
        "create_midi_clip",
    ]
    assert calls[2][1]["index"] == -1
    assert calls[3][1]["track_index"] == 1


def test_stale_complementary_plan_stops_before_creating_anything():
    from abletongpt import server

    calls = []

    def fake_call(command, **params):
        calls.append(command)
        if command == "get_midi_clip_notes":
            return _user_chord_clip()
        raise AssertionError("creation must not start for a stale fingerprint")

    with patch.object(server.bridge, "call", side_effect=fake_call):
        try:
            server.create_complementary_midi_track(
                0,
                0,
                "bass",
                expected_source_fingerprint="stale0000000000",
            )
        except ValueError as exc:
            assert "changed" in str(exc)
        else:
            raise AssertionError("stale source fingerprint must be rejected")

    assert calls == ["get_midi_clip_notes"]


def test_loudness_analysis_reports_bs1770_metrics_and_target_guidance():
    from abletongpt.loudness import analyze_loudness_file

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "tone.wav"
        sample_rate = 48000
        frames = bytearray()
        for sample_index in range(sample_rate * 4):
            value = int(0.1 * 32767 * math.sin(2 * math.pi * 1000 * sample_index / sample_rate))
            frames.extend(struct.pack("<hh", value, value))
        with wave.open(str(path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(frames)

        result = analyze_loudness_file(path, target_lufs=-14.0, target_true_peak_dbtp=-1.0)

    measurements = result["measurements"]
    assert result["file"]["duration_seconds"] == 4.0
    assert result["read_only"] is True
    assert -21.5 < measurements["integrated_lufs"] < -19.5
    assert -20.1 < measurements["sample_peak_dbfs"] < -19.9
    assert measurements["true_peak_dbtp"] >= measurements["sample_peak_dbfs"]
    assert -23.2 < measurements["rms_dbfs"] < -22.8
    assert result["analysis"]["gain_to_target_db"] > 5.0
    assert result["analysis"]["peak_control_likely_required"] is False


def test_loudness_analysis_represents_silence_without_infinity():
    from abletongpt.loudness import analyze_loudness_file

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "silence.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(b"\x00\x00" * 48000)
        result = analyze_loudness_file(path)

    assert result["measurements"]["integrated_lufs"] is None
    assert result["measurements"]["sample_peak_dbfs"] is None
    assert result["analysis"]["gain_to_target_db"] is None
