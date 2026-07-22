from __future__ import absolute_import, print_function, unicode_literals

import json
import os
import platform
import socket
import threading
from functools import partial

from _Framework.ControlSurface import ControlSurface


ALLOWED_NATIVE_INSTRUMENTS = (
    "Drift",
    "Wavetable",
    "Operator",
    "Analog",
    "Meld",
    "Electric",
    "Tension",
    "Collision",
    "Drum Rack",
    "Impulse",
)


def create_instance(c_instance):
    return AbletonGPTControlSurface(c_instance)


class AbletonGPTControlSurface(ControlSurface):
    """Small localhost JSON bridge. Live Object Model access stays on Live's main thread."""

    def __init__(self, c_instance):
        super(AbletonGPTControlSurface, self).__init__(c_instance)
        shared_config = self._load_shared_config()
        self._host = "127.0.0.1"
        self._port = int(os.environ.get("ABLETONGPT_PORT", shared_config.get("port", 9877)))
        self._token = os.environ.get("ABLETONGPT_TOKEN", shared_config.get("token", ""))
        self._stop_event = threading.Event()
        self._server_socket = None
        self._thread = threading.Thread(target=self._serve, name="AbletonGPTBridge")
        self._thread.daemon = True
        self._thread.start()
        self.log_message("AbletonGPT: bridge listening on 127.0.0.1:%d" % self._port)

    @staticmethod
    def _load_shared_config():
        override = os.environ.get("ABLETONGPT_CONFIG")
        if override:
            path = os.path.expanduser(override)
        elif platform.system() == "Darwin":
            path = os.path.expanduser(
                "~/Library/Application Support/AbletonGPT/config.json"
            )
        elif platform.system() == "Windows":
            path = os.path.join(os.environ.get("APPDATA", ""), "AbletonGPT", "config.json")
        else:
            path = os.path.expanduser("~/.config/abletongpt/config.json")
        try:
            with open(path, "r") as config_file:
                data = json.load(config_file)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def disconnect(self):
        self._stop_event.set()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        super(AbletonGPTControlSurface, self).disconnect()

    def _serve(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket = server
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self._host, self._port))
        server.listen(5)
        server.settimeout(0.5)
        while not self._stop_event.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def _handle_client(self, client):
        try:
            client.settimeout(5)
            data = b""
            while b"\n" not in data and len(data) <= 1000000:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
            request = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
            if self._token and request.get("token") != self._token:
                self._send(client, {"ok": False, "error": "unauthorized"})
                return
            self.schedule_message(
                0,
                partial(self._execute_and_reply, request, client),
            )
        except Exception as exc:
            self._send(client, {"ok": False, "error": str(exc)})

    def _execute_and_reply(self, request, client):
        try:
            result = self._execute(request.get("command"), request.get("params") or {})
            self._send(client, {"ok": True, "result": result})
        except Exception as exc:
            self._send(client, {"ok": False, "error": str(exc)})

    @staticmethod
    def _send(client, response):
        try:
            client.sendall((json.dumps(response) + "\n").encode("utf-8"))
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _execute(self, command, params):
        song = self.song()
        if command == "ping":
            return {"connected": True, "app": "Ableton Live"}
        if command == "get_state":
            return {
                "is_playing": bool(song.is_playing),
                "tempo": float(song.tempo),
                "signature": [int(song.signature_numerator), int(song.signature_denominator)],
                "scene_count": len(song.scenes),
                "tracks": [
                    {
                        "index": i,
                        "name": track.name,
                        "volume": float(track.mixer_device.volume.value),
                        "mute": bool(track.mute),
                        "solo": bool(track.solo),
                        "arm": bool(track.arm) if track.can_be_armed else False,
                        "clip_slots": len(track.clip_slots),
                    }
                    for i, track in enumerate(song.tracks)
                ],
            }
        if command == "get_mix_snapshot":
            return {
                "tracks": [self._mix_state(index, track) for index, track in enumerate(song.tracks)],
                "returns": [
                    self._mix_state(index, track)
                    for index, track in enumerate(song.return_tracks)
                ],
                "master": self._mix_state(-1, song.master_track),
                "meter_note": "output_meter_level is a momentary/hold Live meter, not LUFS",
            }
        if command == "browse_presets":
            return self._browse_presets(
                params["category"],
                params.get("path", []),
                int(params.get("max_items", 200)),
            )
        if command == "load_preset":
            return self._load_preset(
                song,
                int(params["track_index"]),
                params["category"],
                params.get("path", []),
                params["name"],
            )
        if command == "create_track":
            track_type = params["track_type"]
            index = int(params.get("index", -1))
            if index == -1:
                index = len(song.tracks)
            if index < 0 or index > len(song.tracks):
                raise IndexError("track insertion index out of range")
            if track_type == "midi":
                song.create_midi_track(index)
            elif track_type == "audio":
                song.create_audio_track(index)
            else:
                raise ValueError("unsupported track type")
            track = song.tracks[index]
            name = params.get("name", "")
            if name:
                track.name = name
            return {
                "index": index,
                "name": track.name,
                "track_type": track_type,
                "total_tracks": len(song.tracks),
            }
        if command == "create_midi_clip":
            track = self._track(song, params["track_index"])
            if not track.has_midi_input:
                raise ValueError("target track is not a MIDI track")
            index = int(params["clip_index"])
            if index < 0 or index >= len(track.clip_slots):
                raise IndexError("clip index out of range")
            slot = track.clip_slots[index]
            if slot.has_clip:
                raise ValueError("target clip slot is not empty")
            length = float(params["length_beats"])
            slot.create_clip(length)
            clip = slot.clip
            clip.name = params.get("name", "AI Sketch")
            notes = params.get("notes", [])
            live_notes = tuple(
                (
                    int(note["pitch"]),
                    float(note["start_time"]),
                    float(note["duration"]),
                    int(note.get("velocity", 100)),
                    bool(note.get("mute", False)),
                )
                for note in notes
            )
            if live_notes:
                clip.set_notes(live_notes)
            return {
                "track": track.name,
                "clip_index": index,
                "clip": clip.name,
                "length_beats": length,
                "note_count": len(live_notes),
            }
        if command == "get_midi_clip_notes":
            track = self._track(song, params["track_index"])
            if not track.has_midi_input:
                raise ValueError("target track is not a MIDI track")
            index = int(params["clip_index"])
            if index < 0 or index >= len(track.clip_slots):
                raise IndexError("clip index out of range")
            slot = track.clip_slots[index]
            if not slot.has_clip or not slot.clip.is_midi_clip:
                raise ValueError("target clip slot does not contain a MIDI clip")
            clip = slot.clip
            payload = clip.get_notes_extended(0, 128, 0.0, float(clip.length))
            source_notes = payload.get("notes", []) if isinstance(payload, dict) else payload
            total_note_count = len(source_notes)
            notes = []
            for source_note in source_notes[:4096]:
                if isinstance(source_note, dict):
                    value = source_note
                else:
                    value = {
                        "pitch": source_note.pitch,
                        "start_time": source_note.start_time,
                        "duration": source_note.duration,
                        "velocity": source_note.velocity,
                        "probability": getattr(source_note, "probability", 1.0),
                    }
                notes.append(
                    {
                        "pitch": int(value["pitch"]),
                        "start_time": float(value["start_time"]),
                        "duration": float(value["duration"]),
                        "velocity": int(value.get("velocity", 100)),
                        "probability": float(value.get("probability", 1.0)),
                    }
                )
            return {
                "track_index": int(params["track_index"]),
                "track": track.name,
                "clip_index": index,
                "clip": clip.name,
                "length_beats": float(clip.length),
                "tempo": float(song.tempo),
                "time_signature": [
                    int(song.signature_numerator),
                    int(song.signature_denominator),
                ],
                "notes": notes,
                "note_count": total_note_count,
                "truncated": total_note_count > len(notes),
            }
        if command == "apply_expression_to_clip":
            track = self._track(song, params["track_index"])
            if not track.has_midi_input:
                raise ValueError("target track is not a MIDI track")
            index = int(params["clip_index"])
            if index < 0 or index >= len(track.clip_slots):
                raise IndexError("clip index out of range")
            slot = track.clip_slots[index]
            if not slot.has_clip or not slot.clip.is_midi_clip:
                raise ValueError("target clip slot does not contain a MIDI clip")
            clip = slot.clip
            length = float(clip.length)
            incoming = params.get("notes", [])
            if len(incoming) > 4096:
                raise ValueError("a clip may contain at most 4096 notes per request")
            new_notes = []
            for note in incoming:
                start = float(note["start_time"])
                duration = float(note["duration"])
                if start < 0.0 or start >= length or duration <= 0.0:
                    raise ValueError("note timing is outside the clip")
                new_notes.append(
                    {
                        "pitch": int(note["pitch"]),
                        "start_time": start,
                        "duration": min(duration, length - start),
                        "velocity": float(note.get("velocity", 100)),
                        "probability": float(note.get("probability", 1.0)),
                        "mute": bool(note.get("mute", False)),
                    }
                )
            # The extended note API (Live 11+) is required so per-note probability
            # survives the round-trip. Refuse clearly on anything older.
            if not hasattr(clip, "add_new_notes"):
                raise RuntimeError(
                    "applying expression requires Live 11 or later (add_new_notes API)"
                )
            # Replace the clip's notes in place: clear the whole clip, then add the
            # performed notes. Note count is unchanged; the user can Undo in Live.
            clip.remove_notes_extended(0, 128, 0.0, length)
            if new_notes:
                clip.add_new_notes({"notes": new_notes})
            return {
                "track": track.name,
                "clip_index": index,
                "clip": clip.name,
                "length_beats": length,
                "note_count": len(new_notes),
            }
        if command == "get_audio_clip_paths":
            track_index = int(params["track_index"])
            track = self._track(song, track_index)
            view = params.get("view", "both")
            if view not in ("session", "arrangement", "both"):
                raise ValueError("view must be session, arrangement, or both")
            clips = []
            total_count = 0
            if view in ("session", "both"):
                for slot_index, slot in enumerate(track.clip_slots):
                    if slot.has_clip and bool(slot.clip.is_audio_clip):
                        total_count += 1
                        if len(clips) < 4096:
                            clips.append(
                                self._audio_clip_state("session", slot_index, slot.clip)
                            )
            if view in ("arrangement", "both"):
                for clip_index, clip in enumerate(track.arrangement_clips):
                    if bool(clip.is_audio_clip):
                        total_count += 1
                        if len(clips) < 4096:
                            clips.append(
                                self._audio_clip_state("arrangement", clip_index, clip)
                            )
            return {
                "track_index": track_index,
                "track": track.name,
                "view": view,
                "clips": clips,
                "clip_count": total_count,
                "truncated": total_count > len(clips),
                "read_only": True,
            }
        if command == "import_audio_clip":
            track = self._track(song, params["track_index"])
            if not track.has_audio_input or track.has_midi_input:
                raise ValueError("target track is not an audio track")
            index = int(params["clip_index"])
            if index < 0 or index >= len(track.clip_slots):
                raise IndexError("clip index out of range")
            slot = track.clip_slots[index]
            if slot.has_clip:
                raise ValueError("target clip slot is not empty")
            slot.create_audio_clip(params["file_path"])
            clip = slot.clip
            clip.name = params.get("name", "AI Vocal Take")
            return {
                "track": track.name,
                "clip_index": index,
                "clip": clip.name,
                "file_path": params["file_path"],
                "length": float(clip.length),
            }
        if command == "get_track_devices":
            track = self._track(song, params["track_index"])
            return {
                "track_index": int(params["track_index"]),
                "track": track.name,
                "devices": [
                    {
                        "index": device_index,
                        "name": device.name,
                        "class_name": device.class_name,
                        "class_display_name": getattr(device, "class_display_name", device.name),
                        "type": int(device.type),
                        "is_active": bool(device.is_active),
                        "parameters": [
                            self._parameter_state(parameter_index, parameter)
                            for parameter_index, parameter in enumerate(device.parameters)
                        ],
                    }
                    for device_index, device in enumerate(track.devices)
                ],
            }
        if command == "add_native_device":
            track = self._track(song, params["track_index"])
            if not hasattr(track, "insert_device"):
                raise RuntimeError("adding devices requires Ableton Live 12.3 or later")
            index = int(params.get("index", -1))
            before_count = len(track.devices)
            if index == -1:
                track.insert_device(params["device_name"])
                index = before_count
            else:
                if index < 0 or index > before_count:
                    raise IndexError("device insertion index out of range")
                track.insert_device(params["device_name"], index)
            if len(track.devices) != before_count + 1:
                raise RuntimeError("Live did not insert the requested device")
            device = track.devices[index]
            return {
                "track": track.name,
                "index": index,
                "name": device.name,
                "class_display_name": getattr(device, "class_display_name", device.name),
                "type": int(device.type),
                "device_count": len(track.devices),
            }
        if command == "insert_first_available_instrument":
            track = self._track(song, params["track_index"])
            if not track.has_midi_input:
                raise ValueError("target track is not a MIDI track")
            if not hasattr(track, "insert_device"):
                raise RuntimeError("adding instruments requires Ableton Live 12.3 or later")
            if any(int(device.type) == 2 for device in track.devices):
                raise ValueError("target track already contains an instrument")
            candidates = params.get("candidates") or []
            if not isinstance(candidates, list) or not candidates or len(candidates) > 8:
                raise ValueError("candidates must contain between 1 and 8 instruments")
            if any(name not in ALLOWED_NATIVE_INSTRUMENTS for name in candidates):
                raise ValueError("candidate is not an allowed native instrument")
            index = int(params.get("index", -1))
            if index < -1 or index > len(track.devices):
                raise IndexError("device insertion index out of range")
            attempted = []
            failures = []
            for candidate in candidates:
                attempted.append(candidate)
                before_devices = list(track.devices)
                try:
                    if index == -1:
                        track.insert_device(candidate)
                    else:
                        track.insert_device(candidate, index)
                except Exception as exc:
                    if len(track.devices) == len(before_devices):
                        failures.append({"name": candidate, "error": str(exc)[:300]})
                        continue
                inserted = [device for device in track.devices if device not in before_devices]
                if len(inserted) != 1:
                    raise RuntimeError("Live did not insert exactly one instrument")
                device = inserted[0]
                if int(device.type) != 2:
                    raise RuntimeError("Live inserted a device that is not an instrument")
                device_index = list(track.devices).index(device)
                return {
                    "track": track.name,
                    "track_index": int(params["track_index"]),
                    "index": device_index,
                    "name": device.name,
                    "class_display_name": getattr(device, "class_display_name", device.name),
                    "type": int(device.type),
                    "requested_candidate": candidate,
                    "fallback_used": candidate != candidates[0],
                    "attempted": attempted,
                    "failed_candidates": failures,
                    "device_count": len(track.devices),
                }
            raise RuntimeError(
                "none of the selected native instruments are available: %s"
                % ", ".join(candidates)
            )
        if command == "set_device_power":
            device = self._device(song, params["track_index"], params["device_index"])
            if not device.parameters:
                raise ValueError("device has no power parameter")
            parameter = device.parameters[0]
            if not parameter.is_enabled:
                raise ValueError("device power parameter is currently locked")
            parameter.value = 1.0 if params["enabled"] else 0.0
            return {
                "device": device.name,
                "enabled": bool(parameter.value >= 0.5),
                "parameter": self._parameter_state(0, parameter),
            }
        if command == "set_device_parameter":
            parameter, device = self._parameter(
                song,
                params["track_index"],
                params["device_index"],
                params["parameter_index"],
            )
            if not parameter.is_enabled:
                raise ValueError("parameter is currently locked or macro-controlled")
            value = float(params["value"])
            if params.get("normalized", False):
                value = float(parameter.min) + value * (float(parameter.max) - float(parameter.min))
            if value < float(parameter.min) or value > float(parameter.max):
                raise ValueError("parameter value out of range")
            parameter.value = value
            return {
                "device": device.name,
                "parameter": self._parameter_state(int(params["parameter_index"]), parameter),
            }
        if command == "reset_device_parameter":
            parameter, device = self._parameter(
                song,
                params["track_index"],
                params["device_index"],
                params["parameter_index"],
            )
            if not parameter.is_enabled:
                raise ValueError("parameter is currently locked or macro-controlled")
            if parameter.is_quantized:
                raise ValueError("quantized parameters do not expose a reliable default value")
            parameter.value = float(parameter.default_value)
            return {
                "device": device.name,
                "parameter": self._parameter_state(int(params["parameter_index"]), parameter),
            }
        if command == "set_transport":
            if params["action"] == "play":
                song.start_playing()
            elif params["action"] == "stop":
                song.stop_playing()
            else:
                raise ValueError("unsupported transport action")
            return {"is_playing": bool(song.is_playing)}
        if command == "set_tempo":
            song.tempo = float(params["bpm"])
            return {"tempo": float(song.tempo)}
        if command == "set_track_volume":
            track = self._track(song, params["track_index"])
            track.mixer_device.volume.value = float(params["volume"])
            return {"track": track.name, "volume": float(track.mixer_device.volume.value)}
        if command == "set_track_pan":
            track = self._track(song, params["track_index"])
            track.mixer_device.panning.value = float(params["pan"])
            return {"track": track.name, "pan": float(track.mixer_device.panning.value)}
        if command == "set_track_mute":
            track = self._track(song, params["track_index"])
            track.mute = bool(params["muted"])
            return {"track": track.name, "muted": bool(track.mute)}
        if command == "set_track_solo":
            track = self._track(song, params["track_index"])
            track.solo = bool(params["soloed"])
            return {"track": track.name, "soloed": bool(track.solo)}
        if command == "set_track_arm":
            track = self._track(song, params["track_index"])
            if not track.can_be_armed:
                raise ValueError("track cannot be armed")
            track.arm = bool(params["armed"])
            return {"track": track.name, "arm": bool(track.arm)}
        if command == "stop_track_clips":
            track = self._track(song, params["track_index"])
            track.stop_all_clips()
            return {"track": track.name, "stopped": True}
        if command == "fire_clip":
            track = self._track(song, params["track_index"])
            index = int(params["clip_index"])
            if index < 0 or index >= len(track.clip_slots):
                raise IndexError("clip index out of range")
            slot = track.clip_slots[index]
            if not slot.has_clip:
                raise ValueError("clip slot is empty")
            slot.fire()
            return {"track": track.name, "clip": slot.clip.name, "fired": True}
        if command == "fire_clip_group":
            index = int(params["clip_index"])
            raw_track_indices = params.get("track_indices")
            if not isinstance(raw_track_indices, list) or not raw_track_indices:
                raise ValueError("track_indices must be a non-empty list")
            if len(raw_track_indices) > 256:
                raise ValueError("track_indices may contain at most 256 entries")
            track_indices = [int(value) for value in raw_track_indices]
            if len(set(track_indices)) != len(track_indices):
                raise ValueError("track_indices must not contain duplicates")

            # Validate the complete group before firing anything. This prevents a
            # malformed request from launching only the first few tracks.
            targets = []
            for track_index in track_indices:
                track = self._track(song, track_index)
                if index < 0 or index >= len(track.clip_slots):
                    raise IndexError("clip index out of range")
                slot = track.clip_slots[index]
                if not slot.has_clip:
                    raise ValueError("clip slot is empty on track: %s" % track.name)
                targets.append((track_index, track, slot))

            # All fire calls happen in the same Live main-thread callback and are
            # quantized against the same launch boundary.
            for _track_index, _track, slot in targets:
                slot.fire()
            return {
                "clip_index": index,
                "launch_mode": "single_command_quantized_group",
                "fired": [
                    {
                        "track_index": track_index,
                        "track": track.name,
                        "clip": slot.clip.name,
                    }
                    for track_index, track, slot in targets
                ],
            }
        if command == "duplicate_clip_to_slot":
            track = self._track(song, params["track_index"])
            source_index = int(params["source_clip_index"])
            destination_index = int(params["destination_clip_index"])
            if source_index < 0 or source_index >= len(track.clip_slots):
                raise IndexError("source clip index out of range")
            if destination_index < 0 or destination_index >= len(track.clip_slots):
                raise IndexError("destination clip index out of range")
            if source_index == destination_index:
                raise ValueError("source and destination clip indices must differ")
            source_slot = track.clip_slots[source_index]
            destination_slot = track.clip_slots[destination_index]
            if not source_slot.has_clip:
                raise ValueError("source clip slot is empty")
            if destination_slot.has_clip:
                raise ValueError("destination clip slot is not empty")
            source_slot.duplicate_clip_to(destination_slot)
            if not destination_slot.has_clip:
                raise RuntimeError("Live did not duplicate the clip")
            name = params.get("name", "")
            if name:
                destination_slot.clip.name = name
            return {
                "track_index": int(params["track_index"]),
                "track": track.name,
                "source_clip_index": source_index,
                "destination_clip_index": destination_index,
                "clip": destination_slot.clip.name,
                "is_audio_clip": bool(destination_slot.clip.is_audio_clip),
                "is_midi_clip": bool(destination_slot.clip.is_midi_clip),
            }
        if command == "fire_scene":
            scene_index = int(params["scene_index"])
            if scene_index < 0 or scene_index >= len(song.scenes):
                raise IndexError("scene index out of range")
            scene = song.scenes[scene_index]
            clips = []
            for track_index, track in enumerate(song.tracks):
                slot = track.clip_slots[scene_index]
                if slot.has_clip:
                    clips.append(
                        {
                            "track_index": track_index,
                            "track": track.name,
                            "clip": slot.clip.name,
                        }
                    )
            scene.fire()
            return {
                "scene_index": scene_index,
                "scene": scene.name,
                "launch_mode": "single_scene_fire",
                "fired": clips,
            }
        if command == "copy_session_clip_to_arrangement":
            track_index = int(params["track_index"])
            clip_index = int(params["clip_index"])
            destination_time = float(params["destination_time_beats"])
            track = self._track(song, track_index)
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("clip index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise ValueError("source clip slot is empty")
            target = self._prepare_arrangement_copy(
                track_index,
                track,
                slot.clip,
                destination_time,
            )
            before_count = len(track.arrangement_clips)
            track.duplicate_clip_to_arrangement(slot.clip, destination_time)
            if len(track.arrangement_clips) != before_count + 1:
                raise RuntimeError("Live did not create exactly one Arrangement clip")
            arrangement_clip = self._find_arrangement_clip(
                track,
                destination_time,
                target["end_time"],
            )
            name = params.get("name", "")
            if name:
                arrangement_clip.name = name
            return {
                "track_index": track_index,
                "track": track.name,
                "source_clip_index": clip_index,
                "source_clip": slot.clip.name,
                "arrangement_clip": arrangement_clip.name,
                "start_time": float(arrangement_clip.start_time),
                "end_time": float(arrangement_clip.end_time),
                "is_audio_clip": bool(arrangement_clip.is_audio_clip),
                "is_midi_clip": bool(arrangement_clip.is_midi_clip),
            }
        if command == "copy_scene_to_arrangement":
            scene_index = int(params["scene_index"])
            destination_time = float(params["destination_time_beats"])
            if scene_index < 0 or scene_index >= len(song.scenes):
                raise IndexError("scene index out of range")
            raw_track_indices = params.get("track_indices")
            if raw_track_indices is None:
                track_indices = list(range(len(song.tracks)))
            else:
                if not isinstance(raw_track_indices, list) or not raw_track_indices:
                    raise ValueError("track_indices must be null or a non-empty list")
                if len(raw_track_indices) > 256:
                    raise ValueError("track_indices may contain at most 256 entries")
                track_indices = [int(value) for value in raw_track_indices]
                if len(set(track_indices)) != len(track_indices):
                    raise ValueError("track_indices must not contain duplicates")

            # Preflight every target before changing the Arrangement. If any
            # track overlaps or is unsupported, nothing is copied.
            targets = []
            skipped_empty_tracks = []
            for track_index in track_indices:
                track = self._track(song, track_index)
                slot = track.clip_slots[scene_index]
                if not slot.has_clip:
                    skipped_empty_tracks.append(track_index)
                    continue
                prepared = self._prepare_arrangement_copy(
                    track_index,
                    track,
                    slot.clip,
                    destination_time,
                )
                targets.append((track_index, track, slot.clip, prepared))
            if not targets:
                raise ValueError("scene contains no copyable clips on the selected tracks")

            copied = []
            for track_index, track, source_clip, prepared in targets:
                before_count = len(track.arrangement_clips)
                track.duplicate_clip_to_arrangement(source_clip, destination_time)
                if len(track.arrangement_clips) != before_count + 1:
                    raise RuntimeError(
                        "Live did not create exactly one Arrangement clip on track: %s"
                        % track.name
                    )
                arrangement_clip = self._find_arrangement_clip(
                    track,
                    destination_time,
                    prepared["end_time"],
                )
                copied.append(
                    {
                        "track_index": track_index,
                        "track": track.name,
                        "source_clip": source_clip.name,
                        "arrangement_clip": arrangement_clip.name,
                        "start_time": float(arrangement_clip.start_time),
                        "end_time": float(arrangement_clip.end_time),
                        "is_audio_clip": bool(arrangement_clip.is_audio_clip),
                        "is_midi_clip": bool(arrangement_clip.is_midi_clip),
                    }
                )
            return {
                "scene_index": scene_index,
                "scene": song.scenes[scene_index].name,
                "destination_time_beats": destination_time,
                "copied": copied,
                "skipped_empty_tracks": skipped_empty_tracks,
                "collision_policy": "reject_before_copy",
            }
        raise ValueError("unsupported command: %s" % command)

    @staticmethod
    def _track(song, index):
        index = int(index)
        if index < 0 or index >= len(song.tracks):
            raise IndexError("track index out of range")
        return song.tracks[index]

    @staticmethod
    def _audio_clip_state(location, index, clip):
        warped = bool(clip.warping)
        state = {
            "location": location,
            "index": int(index),
            "name": clip.name,
            "file_path": str(clip.file_path),
            "warping": warped,
            "looping": bool(clip.looping),
            "length_beats": float(clip.length) if warped else None,
            "sample_length": int(clip.sample_length),
            "sample_rate": float(clip.sample_rate),
            "gain_display": str(clip.gain_display_string),
        }
        if location == "arrangement":
            state["start_time"] = float(clip.start_time)
            state["end_time"] = float(clip.end_time)
        else:
            state["loop_start"] = float(clip.loop_start)
            state["loop_end"] = float(clip.loop_end)
        return state

    @staticmethod
    def _prepare_arrangement_copy(track_index, track, source_clip, destination_time):
        if destination_time < 0.0 or destination_time > 1576800.0:
            raise ValueError("destination_time_beats is outside Live's supported range")
        if bool(getattr(track, "is_frozen", False)):
            raise ValueError("cannot copy to a frozen track: %s" % track.name)
        if bool(source_clip.is_audio_clip) and not bool(source_clip.warping):
            raise ValueError(
                "collision-safe Arrangement copy requires warped audio: %s" % track.name
            )
        duration = float(source_clip.length)
        if duration <= 0.0:
            raise ValueError("source clip has an invalid length: %s" % track.name)
        end_time = destination_time + duration
        if end_time > 1576800.0:
            raise ValueError("copied clip would exceed Live's supported Arrangement range")
        for arrangement_clip in track.arrangement_clips:
            existing_start = float(arrangement_clip.start_time)
            existing_end = float(arrangement_clip.end_time)
            if destination_time < existing_end - 0.000001 and end_time > existing_start + 0.000001:
                raise ValueError(
                    "Arrangement destination overlaps an existing clip on track %d: %s"
                    % (track_index, track.name)
                )
        return {"duration": duration, "end_time": end_time}

    @staticmethod
    def _find_arrangement_clip(track, start_time, expected_end_time):
        matches = [
            clip
            for clip in track.arrangement_clips
            if abs(float(clip.start_time) - start_time) < 0.000001
            and abs(float(clip.end_time) - expected_end_time) < 0.000001
        ]
        if not matches:
            raise RuntimeError("Live created the Arrangement clip at an unexpected time")
        return matches[-1]

    @classmethod
    def _device(cls, song, track_index, device_index):
        track = cls._track(song, track_index)
        device_index = int(device_index)
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("device index out of range")
        return track.devices[device_index]

    @classmethod
    def _parameter(cls, song, track_index, device_index, parameter_index):
        device = cls._device(song, track_index, device_index)
        parameter_index = int(parameter_index)
        if parameter_index < 0 or parameter_index >= len(device.parameters):
            raise IndexError("parameter index out of range")
        return device.parameters[parameter_index], device

    @staticmethod
    def _parameter_state(index, parameter):
        minimum = float(parameter.min)
        maximum = float(parameter.max)
        value = float(parameter.value)
        normalized = 0.0 if maximum == minimum else (value - minimum) / (maximum - minimum)
        try:
            display_value = str(parameter)
        except Exception:
            display_value = str(value)
        result = {
            "index": index,
            "name": parameter.name,
            "value": value,
            "display_value": display_value,
            "normalized_value": normalized,
            "min": minimum,
            "max": maximum,
            "is_enabled": bool(parameter.is_enabled),
            "is_quantized": bool(parameter.is_quantized),
        }
        if parameter.is_quantized:
            result["value_items"] = list(parameter.value_items)
        else:
            result["default_value"] = float(parameter.default_value)
        return result

    @staticmethod
    def _mix_state(index, track):
        mixer = track.mixer_device
        try:
            meter = float(track.output_meter_level)
        except Exception:
            meter = None
        try:
            mute = bool(track.mute)
        except Exception:
            mute = False
        try:
            solo = bool(track.solo)
        except Exception:
            solo = False
        return {
            "index": index,
            "name": track.name,
            "volume": float(mixer.volume.value),
            "pan": float(mixer.panning.value),
            "mute": mute,
            "solo": solo,
            "output_meter_level": meter,
            "sends": [
                {"index": send_index, "value": float(send.value)}
                for send_index, send in enumerate(mixer.sends)
            ],
        }

    #: Top-level Live browser roots we allow enumerating. Each name is a BrowserItem
    #: attribute on ``Application.browser``. Read-only browsing only -- never loads.
    BROWSER_CATEGORIES = (
        "instruments",
        "sounds",
        "drums",
        "audio_effects",
        "midi_effects",
        "samples",
        "plugins",
        "max_for_live",
        "packs",
        "user_library",
    )

    def _resolve_browser_node(self, category, path):
        """Return the BrowserItem at ``category`` descended through ``path`` folder names."""
        if category not in self.BROWSER_CATEGORIES:
            raise ValueError("unknown browser category: %s" % category)
        browser = self.application().browser
        node = getattr(browser, category, None)
        if node is None:
            raise ValueError("this Live version has no '%s' browser category" % category)
        for segment in path:
            match = None
            for child in node.children:
                if child.name == segment and child.is_folder:
                    match = child
                    break
            if match is None:
                raise ValueError("browser folder not found: %s" % segment)
            node = match
        return node

    def _browse_presets(self, category, path, max_items):
        if max_items < 1 or max_items > 1000:
            raise ValueError("max_items must be between 1 and 1000")
        node = self._resolve_browser_node(category, path)

        items = []
        truncated = False
        for child in node.children:
            if len(items) >= max_items:
                truncated = True
                break
            items.append(
                {
                    "name": child.name,
                    "is_folder": bool(child.is_folder),
                    "is_loadable": bool(getattr(child, "is_loadable", False)),
                    "is_device": bool(getattr(child, "is_device", False)),
                    "uri": getattr(child, "uri", None),
                    "source": getattr(child, "source", None),
                }
            )
        return {
            "category": category,
            "path": list(path),
            "items": items,
            "item_count": len(items),
            "truncated": truncated,
            "read_only": True,
        }

    def _load_preset(self, song, track_index, category, path, name):
        track = self._track(song, track_index)
        node = self._resolve_browser_node(category, path)

        target = None
        for child in node.children:
            if child.name == name and not child.is_folder:
                target = child
                break
        if target is None:
            raise ValueError("preset not found: %s" % name)
        if not getattr(target, "is_loadable", False):
            raise ValueError("browser item is not loadable: %s" % name)

        # Safety: never load onto a track that already has an instrument. Loading an
        # instrument preset there could replace the existing one (a destructive change);
        # refusing keeps every load strictly additive, mirroring add_native_device.
        if any(int(device.type) == 2 for device in track.devices):
            raise ValueError(
                "target track already contains an instrument; refusing to load onto it"
            )

        before_count = len(track.devices)
        browser = self.application().browser
        song.view.selected_track = track
        browser.load_item(target)

        after_devices = list(track.devices)
        added = len(after_devices) - before_count
        result = {
            "track": track.name,
            "track_index": track_index,
            "loaded": name,
            "category": category,
            "path": list(path),
            "uri": getattr(target, "uri", None),
            "device_count_before": before_count,
            "device_count_after": len(after_devices),
            "added_device_count": added,
            "devices": [device.name for device in after_devices],
            "verified_single_add": added == 1,
        }
        if added != 1:
            # Live's browser can load asynchronously, so the device list may not reflect the
            # new device yet. Report honestly instead of claiming success we cannot confirm.
            result["note"] = (
                "device count did not increase by exactly one yet; Live may load "
                "asynchronously -- re-check with get_track_devices"
            )
        return result
