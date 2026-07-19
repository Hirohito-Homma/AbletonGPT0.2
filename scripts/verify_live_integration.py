#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import struct
import sys
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abletongpt import server  # noqa: E402
from abletongpt.bridge import AbletonBridge, BridgeConfig  # noqa: E402


REPORT_DIR = ROOT / "outputs"
TEMP_WAV = Path("/private/tmp/abletongpt-verification-vocal.wav")
TEMP_AIFF = Path("/private/tmp/abletongpt-verification-tone.aiff")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_pcm_wav(path: Path, duration: float = 4.0, sample_rate: int = 48000) -> None:
    frames = bytearray()
    for sample_index in range(round(duration * sample_rate)):
        value = round(0.1 * 8388607 * math.sin(2 * math.pi * 440 * sample_index / sample_rate))
        encoded = int(value).to_bytes(3, "little", signed=True)
        frames.extend(encoded)
        frames.extend(encoded)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(3)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def _write_pcm_aiff(path: Path, duration: float = 4.0, sample_rate: int = 48000) -> None:
    frame_count = round(duration * sample_rate)
    samples = bytearray()
    for sample_index in range(frame_count):
        value = round(0.1 * 32767 * math.sin(2 * math.pi * 1000 * sample_index / sample_rate))
        samples.extend(struct.pack(">hh", value, value))
    # IEEE 754 80-bit extended representation of 48000 Hz.
    sample_rate_extended = bytes.fromhex("400ebb80000000000000")
    comm_payload = struct.pack(">hIh", 2, frame_count, 16) + sample_rate_extended
    ssnd_payload = struct.pack(">II", 0, 0) + samples
    body = (
        b"COMM"
        + struct.pack(">I", len(comm_payload))
        + comm_payload
        + b"SSND"
        + struct.pack(">I", len(ssnd_payload))
        + ssnd_payload
    )
    path.write_bytes(b"FORM" + struct.pack(">I", len(body) + 4) + b"AIFF" + body)


def _tool_names() -> list[str]:
    tools = asyncio.run(server.mcp.list_tools())
    return sorted(tool.name for tool in tools)


def _expect_error(function: Callable[[], Any], contains: str) -> str:
    try:
        function()
    except Exception as exc:
        message = str(exc)
        if contains.lower() not in message.lower():
            raise AssertionError("expected error containing %r, received %r" % (contains, message))
        return message
    raise AssertionError("operation unexpectedly succeeded")


class Verification:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.values: dict[str, Any] = {}

    def check(self, name: str, function: Callable[[], Any]) -> Any:
        try:
            detail = function()
            self.results.append({"name": name, "status": "PASS", "detail": detail})
            print("PASS %s" % name, flush=True)
            return detail
        except Exception as exc:
            self.results.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "error": "%s: %s" % (type(exc).__name__, exc),
                }
            )
            print("FAIL %s: %s" % (name, exc), flush=True)
            return None

    def skip(self, name: str, reason: str) -> None:
        self.results.append({"name": name, "status": "SKIP", "reason": reason})
        print("SKIP %s: %s" % (name, reason), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run AbletonGPT end-to-end checks against the currently open Live Set."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required: create non-destructive verification tracks and clips in Live.",
    )
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required because this check creates tracks and clips in Live")

    verification = Verification()
    bridge = AbletonBridge()
    started_at = datetime.now().astimezone()

    initial_state = verification.check("live.connection_and_state", lambda: bridge.call("get_state"))
    if not initial_state:
        raise SystemExit(1)
    initial_tempo = float(initial_state["tempo"])
    initial_playing = bool(initial_state["is_playing"])
    initial_track_count = len(initial_state["tracks"])
    if int(initial_state.get("scene_count", 0)) < 5:
        raise RuntimeError("verification requires at least five Session scenes")

    def beginner_plan() -> dict[str, Any]:
        plan = server.plan_song_sketch(
            "AGPT Beginner Verify", "pop", "uplifting", "C", "major", 110, 4
        )
        assert [track["role"] for track in plan["tracks"]] == [
            "chords",
            "bass",
            "melody",
            "drums",
        ]
        assert all(track["length_beats"] == 16.0 for track in plan["tracks"])
        return {
            "roles": [track["role"] for track in plan["tracks"]],
            "note_counts": {track["role"]: len(track["notes"]) for track in plan["tracks"]},
            "tempo": plan["tempo"],
            "key": "%s %s" % (plan["key"], plan["mode"]),
        }

    verification.check("beginner.plan_four_parts", beginner_plan)

    beginner_created = verification.check(
        "beginner.create_four_live_tracks",
        lambda: server.create_song_sketch(
            "AGPT Beginner Verify", "pop", "uplifting", "C", "major", 110, 4, 0
        ),
    )
    if beginner_created:
        assert len(beginner_created["created"]) == 4
        verification.values["beginner"] = beginner_created

    def professional_plan() -> dict[str, Any]:
        options = {
            "title": "AGPT Pro Verify",
            "progression": [2, 5, 1, 6],
            "genre": "rnb",
            "mood": "chill",
            "key": "D",
            "mode": "minor",
            "tempo": 92,
            "bars": 4,
            "chord_complexity": "ninth",
            "harmonic_rhythm_beats": 2.0,
            "melody_density": 0.55,
            "swing": 0.4,
            "humanize": 0.3,
            "seed": 42,
        }
        first = server.plan_pro_composition(**options)
        second = server.plan_pro_composition(**options)
        straight = server.plan_pro_composition(**{**options, "swing": 0.0, "humanize": 0.0})
        assert first == second
        assert first["professional_settings"]["progression_degrees"] == [2, 5, 1, 6]
        chord_notes = next(track["notes"] for track in first["tracks"] if track["role"] == "chords")
        assert len(chord_notes) == 8 * 5
        melody = next(track["notes"] for track in first["tracks"] if track["role"] == "melody")
        straight_melody = next(
            track["notes"] for track in straight["tracks"] if track["role"] == "melody"
        )
        assert melody != straight_melody
        return {
            "settings": first["professional_settings"],
            "ninth_chord_note_count": len(chord_notes),
            "melody_note_count": len(melody),
            "deterministic": True,
            "swing_humanize_changed_performance": True,
        }

    verification.check("professional.all_controls_and_reproducibility", professional_plan)

    pro_created = verification.check(
        "professional.create_four_live_tracks",
        lambda: server.create_pro_composition(
            "AGPT Pro Verify",
            [2, 5, 1, 6],
            "rnb",
            "chill",
            "D",
            "minor",
            92,
            4,
            "ninth",
            2.0,
            0.55,
            0.4,
            0.3,
            42,
            1,
        ),
    )
    if pro_created:
        assert len(pro_created["created"]) == 4
        verification.values["professional"] = pro_created

    if pro_created:
        pro_melody_track = pro_created["created"][2]["track_index"]

        def part_variation() -> dict[str, Any]:
            created = server.create_part_variation(
                pro_melody_track,
                2,
                "melody",
                "AGPT Pro Verify",
                43,
                [2, 5, 1, 6],
                "rnb",
                "chill",
                "D",
                "minor",
                92,
                4,
                "ninth",
                2.0,
                0.55,
                0.4,
                0.3,
            )
            original = bridge.call(
                "get_midi_clip_notes", track_index=pro_melody_track, clip_index=1
            )
            variation = bridge.call(
                "get_midi_clip_notes", track_index=pro_melody_track, clip_index=2
            )
            assert original["notes"] != variation["notes"]
            return {
                "track_index": pro_melody_track,
                "a_slot": 1,
                "b_slot": 2,
                "a_note_count": original["note_count"],
                "b_note_count": variation["note_count"],
                "different_notes": True,
                "created": created,
            }

        verification.check("part_regeneration.separate_session_slot_ab", part_variation)
    else:
        verification.skip("part_regeneration.separate_session_slot_ab", "pro tracks unavailable")

    def instrument_plan() -> dict[str, Any]:
        plan = server.plan_live_instruments(
            "edm", "dark", ["chords", "bass", "melody", "drums"], "suite"
        )
        assert len(plan["selections"]) == 4
        assert any(item["requires_content"] for item in plan["selections"] if item["role"] == "drums")
        return {
            "edition": plan["live_edition"],
            "selections": [
                {
                    "role": item["role"],
                    "selected": item["selected_instrument"],
                    "candidates": item["candidates"],
                }
                for item in plan["selections"]
            ],
        }

    verification.check("instruments.role_genre_mood_edition_plan", instrument_plan)

    instrument_result = None
    if beginner_created:
        beginner_melody_track = beginner_created["created"][2]["track_index"]
        instrument_result = verification.check(
            "instruments.apply_with_live_availability_fallback",
            lambda: server.apply_live_instrument_selection(
                beginner_melody_track, "melody", "pop", "uplifting", "suite"
            ),
        )
    else:
        verification.skip("instruments.apply_with_live_availability_fallback", "beginner tracks unavailable")

    if beginner_created:
        beginner_chords_track = beginner_created["created"][0]["track_index"]

        def contextual_analysis() -> dict[str, Any]:
            analysis = server.analyze_live_midi_clip(beginner_chords_track, 0, "chords")
            assert analysis["read_only"] is True
            assert analysis["source"]["fingerprint"]
            return analysis

        analysis = verification.check("contextual.analyze_existing_live_midi", contextual_analysis)
        if analysis:
            verification.check(
                "contextual.create_new_complementary_track",
                lambda: server.create_complementary_midi_track(
                    beginner_chords_track,
                    0,
                    "bass",
                    "chords",
                    "pop",
                    "uplifting",
                    "",
                    "",
                    12,
                    "AGPT Context Bass",
                    0,
                    analysis["source"]["fingerprint"],
                ),
            )
        else:
            verification.skip("contextual.create_new_complementary_track", "analysis unavailable")
    else:
        verification.skip("contextual.analyze_existing_live_midi", "beginner tracks unavailable")
        verification.skip("contextual.create_new_complementary_track", "beginner tracks unavailable")

    if beginner_created:
        mixer_track = beginner_created["created"][1]["track_index"]

        def live_controls() -> dict[str, Any]:
            server.set_tempo(123)
            tempo_seen = bridge.call("get_state")["tempo"]
            server.set_track_arm(mixer_track, True)
            arm_seen = bridge.call("get_state")["tracks"][mixer_track]["arm"]
            server.fire_clip(mixer_track, 0)
            play_response = server.set_transport("play")
            playing_seen = bridge.call("get_state")["is_playing"]
            stop_response = server.set_transport("stop")
            stopped_seen = not bridge.call("get_state")["is_playing"]
            server.set_track_arm(mixer_track, False)
            assert tempo_seen == 123.0
            assert arm_seen is True
            assert playing_seen is True and stopped_seen is True
            return {
                "tempo": tempo_seen,
                "record_arm_observed": arm_seen,
                "clip_fired": True,
                "play_then_stop": True,
                "play_response": play_response,
                "stop_response": stop_response,
                "stop_response_was_stale": stop_response["is_playing"] is True,
            }

        verification.check("live_control.tempo_transport_arm_clip", live_controls)

        def mixer_controls() -> dict[str, Any]:
            before = server.get_mix_snapshot()["tracks"][mixer_track]
            server.set_track_volume(mixer_track, 0.63)
            server.set_track_pan(mixer_track, -0.2)
            server.set_track_mute(mixer_track, True)
            server.set_track_solo(mixer_track, True)
            changed = server.get_mix_snapshot()["tracks"][mixer_track]
            assert abs(changed["volume"] - 0.63) < 0.001
            assert abs(changed["pan"] - -0.2) < 0.001
            assert changed["mute"] is True and changed["solo"] is True
            assert "output_meter_level" in changed and isinstance(changed["sends"], list)
            server.set_track_mute(mixer_track, False)
            server.set_track_solo(mixer_track, False)
            server.set_track_volume(mixer_track, before["volume"])
            server.set_track_pan(mixer_track, before["pan"])
            return {
                "changed": changed,
                "send_values_readable": True,
                "send_write_tool_available": "set_track_send" in _tool_names(),
                "restored": True,
            }

        verification.check("mix.volume_pan_mute_solo_send_meter_snapshot", mixer_controls)
    else:
        verification.skip("live_control.tempo_transport_arm_clip", "beginner tracks unavailable")
        verification.skip("mix.volume_pan_mute_solo_send_meter_snapshot", "beginner tracks unavailable")

    if beginner_created:
        effect_track = beginner_created["created"][2]["track_index"]

        def effects() -> dict[str, Any]:
            inserted = server.add_native_device(effect_track, "Auto Filter", -1)
            device_index = inserted["index"]
            listed = server.get_track_devices(effect_track)
            target = listed["devices"][device_index]
            off = server.set_device_power(effect_track, device_index, False)
            on = server.set_device_power(effect_track, device_index, True)
            parameter = next(
                item
                for item in target["parameters"][1:]
                if item["is_enabled"] and not item["is_quantized"]
            )
            changed = server.set_device_parameter(
                effect_track, device_index, parameter["index"], 0.35, True
            )
            reset = server.reset_device_parameter(effect_track, device_index, parameter["index"])
            assert off["enabled"] is False and on["enabled"] is True
            return {
                "inserted": inserted,
                "listed_device_count": len(listed["devices"]),
                "power_cycle": True,
                "parameter": parameter["name"],
                "normalized_value_after_change": changed["parameter"]["normalized_value"],
                "value_after_reset": reset["parameter"]["value"],
            }

        verification.check("effects.insert_list_power_parameter_reset", effects)
    else:
        verification.skip("effects.insert_list_power_parameter_reset", "beginner tracks unavailable")

    def vocal_plan() -> dict[str, Any]:
        plan = server.plan_ai_vocal(
            "AGPT Vocal Verify", "あしたへ進もう", "pop", "uplifting", "C", "major", 110, 4, 0.7, 7
        )
        assert plan["language_hint"] == "ja"
        assert len(plan["midi_notes"]) == len(plan["vocal_events"])
        assert plan["render_contract"]["sample_rate"] == 48000
        assert plan["render_contract"]["bit_depth"] == 24
        return {
            "language": plan["language_hint"],
            "event_count": len(plan["vocal_events"]),
            "render_contract": plan["render_contract"],
        }

    verification.check("vocal.lyrics_guide_render_contract", vocal_plan)
    verification.check(
        "vocal.create_live_midi_guide",
        lambda: server.create_vocal_guide(
            "AGPT Vocal Verify", "あしたへ進もう", "pop", "uplifting", "C", "major", 110, 4, 0.7, 7, 3
        ),
    )

    def audio_files() -> dict[str, Any]:
        _write_pcm_wav(TEMP_WAV)
        _write_pcm_aiff(TEMP_AIFF)
        return {"wav": str(TEMP_WAV), "aiff": str(TEMP_AIFF)}

    generated_audio = verification.check("audio.generate_verification_wav_and_aiff", audio_files)

    if generated_audio:
        verification.check(
            "vocal.import_rendered_wav_to_new_audio_track",
            lambda: server.import_vocal_take(
                str(TEMP_WAV), "AGPT Vocal Take", "AGPT Placeholder Render", 4
            ),
        )

        def loudness() -> dict[str, Any]:
            wav_before = _sha256(TEMP_WAV)
            aiff_before = _sha256(TEMP_AIFF)
            wav_result = server.analyze_audio_loudness(str(TEMP_WAV), -14.0, -1.0)
            aiff_result = server.analyze_audio_loudness(str(TEMP_AIFF), -14.0, -1.0)
            assert wav_result["read_only"] is True and aiff_result["read_only"] is True
            assert wav_before == _sha256(TEMP_WAV) and aiff_before == _sha256(TEMP_AIFF)
            required = {
                "integrated_lufs",
                "max_momentary_lufs",
                "max_short_term_lufs",
                "loudness_range_lu",
                "sample_peak_dbfs",
                "true_peak_dbtp",
                "rms_dbfs",
                "crest_factor_db",
            }
            assert required <= set(wav_result["measurements"])
            return {
                "wav": wav_result,
                "aiff": aiff_result,
                "source_hashes_unchanged": True,
            }

        verification.check("loudness.wav_aiff_all_metrics_read_only", loudness)
    else:
        verification.skip("vocal.import_rendered_wav_to_new_audio_track", "audio generation failed")
        verification.skip("loudness.wav_aiff_all_metrics_read_only", "audio generation failed")

    def safety() -> dict[str, Any]:
        names = _tool_names()
        config = BridgeConfig.load()
        wrong_token = _expect_error(
            lambda: AbletonBridge(
                BridgeConfig(
                    host=config.host,
                    port=config.port,
                    token="definitely-wrong-verification-token",
                    timeout=config.timeout,
                )
            ).call("ping"),
            "unauthorized",
        )
        unsupported_delete = _expect_error(
            lambda: bridge.call("delete_track", track_index=0), "unsupported command"
        )
        unsupported_code = _expect_error(
            lambda: bridge.call("execute_python", code="1+1"), "unsupported command"
        )
        invalid_tempo = _expect_error(lambda: server.set_tempo(19), "between 20 and 999")
        invalid_note = _expect_error(
            lambda: server.create_midi_clip(
                0,
                0,
                "Invalid",
                4.0,
                [{"pitch": 128, "start_time": 0.0, "duration": 1.0, "velocity": 100}],
            ),
            "pitch",
        )
        overwrite = None
        if beginner_created:
            overwrite = _expect_error(
                lambda: server.create_midi_clip(
                    beginner_created["created"][0]["track_index"],
                    0,
                    "Must Not Overwrite",
                    4.0,
                    [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}],
                ),
                "not empty",
            )
        destructive = [name for name in names if any(word in name for word in ("delete", "remove", "overwrite", "save_set", "execute"))]
        assert config.host == "127.0.0.1"
        assert not destructive
        return {
            "bridge_host": config.host,
            "shared_token_configured": bool(config.token),
            "wrong_token_rejected": wrong_token,
            "delete_command_rejected": unsupported_delete,
            "code_execution_command_rejected": unsupported_code,
            "invalid_tempo_rejected": invalid_tempo,
            "invalid_note_rejected": invalid_note,
            "occupied_clip_overwrite_rejected": overwrite,
            "mcp_tool_count": len(names),
            "destructive_or_code_tools": destructive,
        }

    verification.check("safety.localhost_token_validation_no_destructive_surface", safety)

    def restore_transport() -> dict[str, Any]:
        server.set_tempo(initial_tempo)
        server.set_transport("play" if initial_playing else "stop")
        state = bridge.call("get_state")
        assert state["tempo"] == initial_tempo
        assert state["is_playing"] is initial_playing
        return {"tempo": state["tempo"], "is_playing": state["is_playing"]}

    verification.check("cleanup.restore_initial_tempo_and_transport", restore_transport)
    final_state = verification.check("final.live_state", lambda: bridge.call("get_state"))

    finished_at = datetime.now().astimezone()
    pass_count = sum(item["status"] == "PASS" for item in verification.results)
    fail_count = sum(item["status"] == "FAIL" for item in verification.results)
    skip_count = sum(item["status"] == "SKIP" for item in verification.results)
    report = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "summary": {"passed": pass_count, "failed": fail_count, "skipped": skip_count},
        "initial_live_state": initial_state,
        "final_live_state": final_state,
        "tracks_added": (
            len(final_state["tracks"]) - initial_track_count if final_state else None
        ),
        "results": verification.results,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / ("live_verification_%s.json" % started_at.strftime("%Y%m%d_%H%M%S"))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT %s" % report_path, flush=True)
    print("SUMMARY pass=%d fail=%d skip=%d" % (pass_count, fail_count, skip_count), flush=True)
    raise SystemExit(1 if fail_count else 0)


if __name__ == "__main__":
    main()
