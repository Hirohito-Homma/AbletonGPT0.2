"""Runtime-shape tests for the in-Live Remote Script.

Live's ``_Framework`` module is unavailable under normal pytest, so this file
installs a minimal import stub and exercises only the command logic that does not
need a real Live process.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOTE_SCRIPT = ROOT / "ableton_remote_script" / "AbletonGPT" / "__init__.py"


def _load_remote_script():
    live = types.ModuleType("Live")

    class MidiNoteSpecification(dict):
        def __init__(self, **values):
            super().__init__(values)

    live.Clip = types.SimpleNamespace(MidiNoteSpecification=MidiNoteSpecification)

    framework = types.ModuleType("_Framework")
    control_surface_module = types.ModuleType("_Framework.ControlSurface")

    class ControlSurface:
        pass

    control_surface_module.ControlSurface = ControlSurface
    module_names = ("Live", "_Framework", "_Framework.ControlSurface")
    missing = object()
    previous_modules = {
        name: sys.modules.get(name, missing) for name in module_names
    }
    try:
        sys.modules["Live"] = live
        sys.modules["_Framework"] = framework
        sys.modules["_Framework.ControlSurface"] = control_surface_module

        spec = importlib.util.spec_from_file_location(
            "abletongpt_remote_script_test", REMOTE_SCRIPT
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, previous in previous_modules.items():
            if previous is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


class _Clip:
    is_midi_clip = True
    length = 4.0
    name = "Test Clip"

    def __init__(self, notes, fail_first_add=False):
        self.notes = [dict(note) for note in notes]
        self.fail_first_add = fail_first_add
        self.add_calls = 0
        self.last_add_notes = ()

    def get_notes_extended(self, *_args):
        return {"notes": [dict(note) for note in self.notes]}

    def remove_notes_extended(self, *_args):
        self.notes = []

    def add_new_notes(self, notes):
        assert isinstance(notes, tuple)
        self.add_calls += 1
        self.last_add_notes = notes
        if self.fail_first_add and self.add_calls == 1:
            raise TypeError("simulated Live conversion failure")
        self.notes = [dict(note) for note in notes]


class _Slot:
    def __init__(self, clip):
        self.has_clip = True
        self.clip = clip


class _Track:
    name = "Test Track"
    has_midi_input = True

    def __init__(self, clip):
        self.clip_slots = [_Slot(clip)]


class _Song:
    def __init__(self, clip):
        self.tracks = [_Track(clip)]


def _surface_for(module, clip):
    surface = module.AbletonGPTControlSurface.__new__(
        module.AbletonGPTControlSurface
    )
    song = _Song(clip)
    surface.song = lambda: song
    return surface


def _note(pitch=60, velocity=90, probability=1.0):
    return {
        "pitch": pitch,
        "start_time": 0.0,
        "duration": 1.0,
        "velocity": velocity,
        "probability": probability,
        "velocity_deviation": 0.0,
        "release_velocity": 64.0,
        "mute": False,
    }


def test_remote_script_uses_live_instrument_type_one():
    module = _load_remote_script()
    instrument = types.SimpleNamespace(type=1)
    audio_effect = types.SimpleNamespace(type=2)

    assert module.AbletonGPTControlSurface._is_instrument(instrument) is True
    assert module.AbletonGPTControlSurface._is_instrument(audio_effect) is False


def test_expression_apply_passes_live_note_specifications_without_wrapper():
    module = _load_remote_script()
    clip = _Clip([_note()])
    surface = _surface_for(module, clip)
    replacement = _note(pitch=62, velocity=101, probability=0.8)

    result = surface._execute(
        "apply_expression_to_clip",
        {
            "track_index": 0,
            "clip_index": 0,
            "notes": [replacement],
        },
    )

    assert clip.notes == [replacement]
    assert all(
        isinstance(note, module.Live.Clip.MidiNoteSpecification)
        for note in clip.last_add_notes
    )
    assert result["note_count"] == 1
    assert result["rollback_protected"] is True


def test_expression_apply_restores_source_notes_when_live_rejects_add():
    module = _load_remote_script()
    original = _note(pitch=65, velocity=88, probability=0.7)
    clip = _Clip([original], fail_first_add=True)
    surface = _surface_for(module, clip)

    try:
        surface._execute(
            "apply_expression_to_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "notes": [_note(pitch=67)],
            },
        )
    except TypeError as exc:
        assert "simulated Live conversion failure" in str(exc)
    else:
        raise AssertionError("the simulated Live conversion failure must propagate")

    assert clip.notes == [original]
    assert clip.add_calls == 2


def test_note_edit_allows_reviewed_note_count_change():
    module = _load_remote_script()
    original = _note(pitch=60)
    clip = _Clip([original])
    surface = _surface_for(module, clip)
    first = _note(pitch=60)
    first["duration"] = 0.5
    second = _note(pitch=60)
    second["start_time"] = 0.5
    second["duration"] = 0.5

    result = surface._execute(
        "apply_expression_to_clip",
        {
            "track_index": 0,
            "clip_index": 0,
            "notes": [first, second],
            "expected_source_note_count": 1,
            "allow_note_count_change": True,
        },
    )

    assert clip.notes == [first, second]
    assert result["source_note_count"] == 1
    assert result["note_count"] == 2
    assert result["note_count_changed"] is True
    assert result["rollback_protected"] is True


def test_note_count_change_restores_source_notes_when_live_rejects_add():
    module = _load_remote_script()
    original = _note(pitch=64, velocity=87, probability=0.75)
    clip = _Clip([original], fail_first_add=True)
    surface = _surface_for(module, clip)

    try:
        surface._execute(
            "apply_expression_to_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "notes": [_note(pitch=64), _note(pitch=66)],
                "expected_source_note_count": 1,
                "allow_note_count_change": True,
            },
        )
    except TypeError as exc:
        assert "simulated Live conversion failure" in str(exc)
    else:
        raise AssertionError("the simulated Live conversion failure must propagate")

    assert clip.notes == [original]
    assert clip.add_calls == 2


def test_note_count_change_requires_reviewed_source_count():
    module = _load_remote_script()
    original = _note(pitch=67)
    clip = _Clip([original])
    surface = _surface_for(module, clip)

    try:
        surface._execute(
            "apply_expression_to_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "notes": [_note(pitch=67), _note(pitch=69)],
                "allow_note_count_change": True,
            },
        )
    except ValueError as exc:
        assert "requires expected_source_note_count" in str(exc)
    else:
        raise AssertionError("the reviewed source count must be required")

    assert clip.notes == [original]
    assert clip.add_calls == 0


def test_note_count_change_rejects_stale_source_count():
    module = _load_remote_script()
    original = _note(pitch=71)
    clip = _Clip([original])
    surface = _surface_for(module, clip)

    try:
        surface._execute(
            "apply_expression_to_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "notes": [_note(pitch=71), _note(pitch=72)],
                "expected_source_note_count": 2,
                "allow_note_count_change": True,
            },
        )
    except ValueError as exc:
        assert "note count changed before apply" in str(exc)
    else:
        raise AssertionError("a stale source count must be rejected")

    assert clip.notes == [original]
    assert clip.add_calls == 0


def test_note_count_change_rejects_invalid_source_count():
    module = _load_remote_script()
    original = _note(pitch=72)
    clip = _Clip([original])
    surface = _surface_for(module, clip)

    try:
        surface._execute(
            "apply_expression_to_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "notes": [_note(pitch=72), _note(pitch=74)],
                "expected_source_note_count": 1.5,
                "allow_note_count_change": True,
            },
        )
    except ValueError as exc:
        assert "must be a non-negative integer" in str(exc)
    else:
        raise AssertionError("a non-integer source count must be rejected")

    assert clip.notes == [original]
    assert clip.add_calls == 0


def test_note_count_change_may_not_clear_nonempty_clip():
    module = _load_remote_script()
    original = _note(pitch=73)
    clip = _Clip([original])
    surface = _surface_for(module, clip)

    try:
        surface._execute(
            "apply_expression_to_clip",
            {
                "track_index": 0,
                "clip_index": 0,
                "notes": [],
                "expected_source_note_count": 1,
                "allow_note_count_change": True,
            },
        )
    except ValueError as exc:
        assert "may not clear the clip" in str(exc)
    else:
        raise AssertionError("note editing must not clear a nonempty clip")

    assert clip.notes == [original]
    assert clip.add_calls == 0


def test_expression_apply_rejects_note_count_change_before_clearing_clip():
    module = _load_remote_script()
    original = _note(pitch=69)
    clip = _Clip([original])
    surface = _surface_for(module, clip)

    try:
        surface._execute(
            "apply_expression_to_clip",
            {"track_index": 0, "clip_index": 0, "notes": []},
        )
    except ValueError as exc:
        assert "preserve the source note count" in str(exc)
    else:
        raise AssertionError("a note-count-changing replacement must be rejected")

    assert clip.notes == [original]
    assert clip.add_calls == 0


class _ArrangementClip:
    def __init__(self, name, start, end, is_audio=False, muted=False):
        self.name = name
        self.start_time = start
        self.end_time = end
        self.is_audio_clip = is_audio
        self.is_midi_clip = not is_audio
        self.muted = muted


class _ArrangementTrack:
    name = "Arr Track"

    def __init__(self, arrangement_clips):
        self.arrangement_clips = list(arrangement_clips)


class _ArrangementSong:
    def __init__(self, track):
        self.tracks = [track]


def _arrangement_surface(module, track):
    surface = module.AbletonGPTControlSurface.__new__(
        module.AbletonGPTControlSurface
    )
    song = _ArrangementSong(track)
    surface.song = lambda: song
    return surface


def test_get_arrangement_clips_summarises_midi_and_audio():
    module = _load_remote_script()
    track = _ArrangementTrack(
        [
            _ArrangementClip("Intro", 0.0, 16.0),
            _ArrangementClip("Drums", 16.0, 32.0, is_audio=True, muted=True),
        ]
    )
    surface = _arrangement_surface(module, track)

    result = surface._execute("get_arrangement_clips", {"track_index": 0})

    assert result["read_only"] is True
    assert result["clip_count"] == 2
    assert result["truncated"] is False
    first, second = result["clips"]
    assert first == {
        "index": 0,
        "name": "Intro",
        "start_time": 0.0,
        "end_time": 16.0,
        "length_beats": 16.0,
        "is_audio_clip": False,
        "is_midi_clip": True,
        "muted": False,
    }
    assert second["is_audio_clip"] is True
    assert second["muted"] is True
    assert second["length_beats"] == 16.0


def _dispatch_surface(module, timeout):
    surface = module.AbletonGPTControlSurface.__new__(
        module.AbletonGPTControlSurface
    )
    surface._main_thread_timeout = timeout
    surface._token = ""
    sent = []
    surface._send = lambda client, response: sent.append(response)
    surface.log_message = lambda *args, **kwargs: None
    return surface, sent


def test_dispatch_returns_result_when_main_thread_runs():
    module = _load_remote_script()
    surface, sent = _dispatch_surface(module, timeout=5.0)
    surface._execute = lambda command, params: {"echo": command}
    # A cooperative scheduler that runs the callback immediately, as Live's main
    # thread would for a fast command.
    surface.schedule_message = lambda delay, callback: callback()

    surface._dispatch({"command": "ping", "params": {}}, client=object())

    assert sent == [{"ok": True, "result": {"echo": "ping"}}]


def test_dispatch_releases_client_when_main_thread_never_runs():
    module = _load_remote_script()
    surface, sent = _dispatch_surface(module, timeout=0.05)
    pending = []
    # Simulate a wedged main thread: the callback is scheduled but never invoked.
    surface.schedule_message = lambda delay, callback: pending.append(callback)
    surface._execute = lambda command, params: {"echo": command}

    surface._dispatch({"command": "copy_session_clip_to_arrangement", "params": {}}, client=object())

    assert len(sent) == 1
    assert sent[0]["ok"] is False
    assert sent[0]["timeout"] is True

    # The main thread finishing late must not send a second, conflicting reply.
    pending[0]()
    assert len(sent) == 1


class _Cue:
    def __init__(self, time, name=""):
        self.time = time
        self.name = name


class _LocatorSong:
    """A Song modelling how Live actually moves the Arrangement transport.

    ``set_or_delete_cue`` acts on ``current_song_time``. Assigning to that
    property does not move the transport (measured against Live 12.4), and
    assigning to ``start_time`` moves the start marker instead. ``jump_by`` is
    the documented way to set a new playing position relative to the current
    one. ``transport_is_stuck`` models the failure this guards against.
    """

    def __init__(self, transport_is_stuck=False, start=0.0):
        self._time = start
        self.start_time = start
        self.transport_is_stuck = transport_is_stuck
        self.cue_points = []
        self.toggle_calls = 0
        self.jumps = []
        self.is_playing = False
        self.tempo = 120.0

    @property
    def current_song_time(self):
        return self._time

    @current_song_time.setter
    def current_song_time(self, value):
        # Live ignores this here; the tests must not depend on it working.
        pass

    def jump_by(self, delta):
        self.jumps.append(delta)
        if not self.transport_is_stuck:
            self._time = self._time + float(delta)

    def set_or_delete_cue(self):
        self.toggle_calls += 1
        for cue in list(self.cue_points):
            if abs(cue.time - self._time) <= 1e-4:
                self.cue_points.remove(cue)
                return
        self.cue_points.append(_Cue(self._time))


def _locator_surface():
    module = _load_remote_script()
    return module.AbletonGPTControlSurface.__new__(module.AbletonGPTControlSurface)


def test_add_locators_places_cues_at_the_requested_beats():
    surface = _locator_surface()
    song = _LocatorSong(start=512.0)

    result = surface._add_locators(
        song, [{"time": 0.0, "name": "intro"}, {"time": 64.0, "name": "drop"}]
    )

    assert result["created_count"] == 2
    assert sorted(cue.time for cue in song.cue_points) == [0.0, 64.0]
    assert [cue.name for cue in song.cue_points] == ["intro", "drop"]
    # the transport is put back where it was found
    assert song.current_song_time == 512.0


def test_add_locators_never_deletes_when_the_playhead_is_stuck():
    """The guard that keeps a broken playhead from toggling cues off.

    Without it, every call lands on whatever position the transport is parked
    at: the first creates a cue there, the second deletes it again.
    """
    surface = _locator_surface()
    song = _LocatorSong(transport_is_stuck=True, start=512.0)
    existing = _Cue(512.0, "someone else's locator")
    song.cue_points.append(existing)

    result = surface._add_locators(
        song, [{"time": 0.0, "name": "intro"}, {"time": 64.0, "name": "drop"}]
    )

    assert result["created_count"] == 0
    assert result["skipped_count"] == 2
    assert all("transport stayed at" in item["reason"] for item in result["skipped"])
    # nothing was toggled, so the pre-existing locator survives untouched
    assert song.toggle_calls == 0
    assert song.cue_points == [existing]


def test_transport_state_reports_positions_and_cues_without_changing_them():
    surface = _locator_surface()
    song = _LocatorSong(start=512.0)
    song.cue_points.append(_Cue(64.0, "2 drop"))
    song.cue_points.append(_Cue(0.0, "1 intro"))
    state = surface._get_transport_state(song)

    assert state["current_song_time"] == 512.0
    assert state["read_only"] is True
    # cues come back sorted by time so a caller can compare against a plan
    assert [cue["time"] for cue in state["cue_points"]] == [0.0, 64.0]
    assert [cue["name"] for cue in state["cue_points"]] == ["1 intro", "2 drop"]
    assert state["cue_count"] == 2
    # nothing was touched
    assert song.toggle_calls == 0
    assert song.jumps == []
    assert song.current_song_time == 512.0


def test_transport_state_tolerates_properties_a_live_version_lacks():
    surface = _locator_surface()

    class _Minimal(_LocatorSong):
        @property
        def song_length(self):
            raise AttributeError("not in this Live version")

    song = _Minimal(start=8.0)

    state = surface._get_transport_state(song)

    assert state["song_length"] is None
    assert state["current_song_time"] == 8.0


class _BrowserItem:
    def __init__(self, name, is_folder=False, is_loadable=True):
        self.name = name
        self.is_folder = is_folder
        self.is_loadable = is_loadable
        self.children = []


class _PresetTrack:
    def __init__(self, devices):
        self.name = "Chords"
        self.devices = list(devices)


class _PresetSurface:
    """Just enough surface to exercise _load_preset's guard."""

    def __init__(self, module, track, item):
        self._module = module
        self._track = track
        self._item = item
        self.loaded = []
        self.BROWSER_CATEGORIES = module.AbletonGPTControlSurface.BROWSER_CATEGORIES
        self.EFFECT_ONLY_CATEGORIES = module.AbletonGPTControlSurface.EFFECT_ONLY_CATEGORIES

    _is_instrument = staticmethod(
        lambda device: int(device.type) == 1
    )

    def _track_lookup(self, song, index):
        return self._track

    def _resolve_browser_node(self, category, path):
        node = _BrowserItem("root", is_folder=True)
        node.children = [self._item]
        return node

    def application(self):
        surface = self

        class _Browser:
            def load_item(self, item):
                surface.loaded.append(item.name)
                surface._track.devices.append(types.SimpleNamespace(type=2, name=item.name))

        return types.SimpleNamespace(browser=_Browser())


def _preset_surface(devices, item_name="Delay", category_item=None):
    module = _load_remote_script()
    track = _PresetTrack(devices)
    item = category_item or _BrowserItem(item_name)
    surface = module.AbletonGPTControlSurface.__new__(module.AbletonGPTControlSurface)
    helper = _PresetSurface(module, track, item)
    surface._resolve_browser_node = helper._resolve_browser_node
    surface.application = helper.application
    surface._track = lambda song, index: track
    song = types.SimpleNamespace(view=types.SimpleNamespace(selected_track=None))
    return surface, track, helper, song


def test_an_effect_may_be_loaded_onto_a_track_that_already_has_an_instrument():
    """A delay after a synth is ordinary signal-chain work and replaces nothing."""
    instrument = types.SimpleNamespace(type=1, name="Wavetable")
    surface, track, helper, song = _preset_surface([instrument])

    result = surface._load_preset(song, 0, "audio_effects", [], "Delay")

    assert helper.loaded == ["Delay"]
    assert result["added_device_count"] == 1
    # the instrument is still there, first in the chain
    assert track.devices[0] is instrument


def test_an_instrument_preset_is_still_refused_on_a_track_that_has_one():
    instrument = types.SimpleNamespace(type=1, name="Wavetable")
    surface, track, helper, song = _preset_surface([instrument], item_name="Operator")

    try:
        surface._load_preset(song, 0, "instruments", [], "Operator")
    except ValueError as exc:
        assert "already contains an instrument" in str(exc)
    else:
        raise AssertionError("loading an instrument over an instrument must be refused")

    assert helper.loaded == []
    assert track.devices == [instrument]


def test_an_instrument_still_loads_onto_an_empty_track():
    surface, track, helper, song = _preset_surface([], item_name="Operator")

    surface._load_preset(song, 0, "instruments", [], "Operator")

    assert helper.loaded == ["Operator"]


class _Envelope:
    def __init__(self):
        self.steps = []

    def insert_step(self, start, length, value):
        self.steps.append((start, length, value))

    def value_at_time(self, time):
        """Left-continuous, like Live: on a boundary this returns the step ending there."""
        for start, length, value in self.steps:
            if start < time <= start + length:
                return value
        return 0.0


class _EnvelopeClip:
    def __init__(self, arrangement=False):
        self.name = "KIHACHI Chords (full)"
        self.arrangement = arrangement
        self.envelopes = {}

    def automation_envelope(self, parameter):
        # Live returns None for Arrangement clips, and None when none exists yet.
        if self.arrangement:
            return None
        return self.envelopes.get(id(parameter))

    def create_automation_envelope(self, parameter):
        if self.arrangement:
            return None
        envelope = _Envelope()
        self.envelopes[id(parameter)] = envelope
        return envelope


class _EnvelopeSlot:
    def __init__(self, clip):
        self.clip = clip
        self.has_clip = clip is not None


class _EnvelopeTrack:
    def __init__(self, clip, parameter):
        self.name = "KIHACHI Chords"
        self.clip_slots = [_EnvelopeSlot(clip)]
        self.devices = [types.SimpleNamespace(name="Echo", parameters=[parameter])]


def _envelope_surface(clip, parameter):
    module = _load_remote_script()
    surface = module.AbletonGPTControlSurface.__new__(module.AbletonGPTControlSurface)
    track = _EnvelopeTrack(clip, parameter)
    surface._track = lambda song, index: track
    surface._parameter = lambda song, t, d, p: (parameter, track.devices[0])
    return surface, track


def _dry_wet():
    return types.SimpleNamespace(name="Dry Wet", min=0.0, max=1.0, is_enabled=True)


def test_clip_envelope_writes_steps_and_reads_them_back():
    clip = _EnvelopeClip()
    parameter = _dry_wet()
    surface, _track = _envelope_surface(clip, parameter)

    result = surface._set_clip_envelope(
        None,
        {
            "track_index": 3, "clip_index": 0, "device_index": 1, "parameter_index": 52,
            "steps": [
                {"start": 0.0, "length": 64.0, "value": 0.30},
                {"start": 320.0, "length": 64.0, "value": 1.00},
            ],
        },
    )

    assert result["step_count"] == 2
    assert result["parameter"] == "Dry Wet"
    # the write is verified by reading the envelope back, not assumed
    assert [s["value_at_time"] for s in result["steps"]] == [0.30, 1.00]
    assert result["verified_step_count"] == 2
    assert all(step["matches"] for step in result["steps"])


def test_clip_envelope_refuses_values_outside_the_parameter_range():
    clip = _EnvelopeClip()
    parameter = _dry_wet()
    surface, _track = _envelope_surface(clip, parameter)

    try:
        surface._set_clip_envelope(
            None,
            {"track_index": 3, "clip_index": 0, "device_index": 1, "parameter_index": 52,
             "steps": [{"start": 0.0, "length": 4.0, "value": 1.5}]},
        )
    except ValueError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("an out-of-range value must be refused")

    # nothing was written, not even the valid steps of a partially bad batch
    assert clip.envelopes == {}


def test_clip_envelope_says_so_when_live_refuses_an_arrangement_clip():
    """Live documents automation_envelope as returning None for Arrangement clips."""
    clip = _EnvelopeClip(arrangement=True)
    parameter = _dry_wet()
    surface, _track = _envelope_surface(clip, parameter)

    try:
        surface._set_clip_envelope(
            None,
            {"track_index": 3, "clip_index": 0, "device_index": 1, "parameter_index": 52,
             "steps": [{"start": 0.0, "length": 4.0, "value": 0.5}]},
        )
    except ValueError as exc:
        assert "Session clips only" in str(exc)
    else:
        raise AssertionError("an Arrangement clip must be reported, not silently skipped")


def test_clip_envelope_refuses_an_empty_slot():
    parameter = _dry_wet()
    surface, track = _envelope_surface(None, parameter)
    track.clip_slots = [_EnvelopeSlot(None)]

    try:
        surface._set_clip_envelope(
            None,
            {"track_index": 3, "clip_index": 0, "device_index": 1, "parameter_index": 52,
             "steps": [{"start": 0.0, "length": 4.0, "value": 0.5}]},
        )
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("an empty clip slot must be refused")


class _Send:
    """A Live send: a DeviceParameter on the track's mixer, like volume."""

    def __init__(self, value=0.0, enabled=True):
        self.value = value
        self.min = 0.0
        self.max = 1.0
        self.is_enabled = enabled

    def __str__(self):
        return "%.1f %%" % (self.value * 100.0)


class _Mixer:
    def __init__(self, sends):
        self.sends = sends


class _SendTrack:
    def __init__(self, name, sends):
        self.name = name
        self.mixer_device = _Mixer(sends)


class _SendSong:
    def __init__(self, sends, returns=("A-Reverb", "B-Delay")):
        self.tracks = [_SendTrack("KIHACHI Chords", sends)]
        self.return_tracks = [_SendTrack(name, []) for name in returns]
        self.created = 0

    def create_return_track(self):
        self.created += 1
        self.return_tracks.append(_SendTrack("C-Return", []))


def _send_surface(song):
    """A surface with only what these commands touch: song() and the real _track."""

    module = _load_remote_script()
    surface = module.AbletonGPTControlSurface.__new__(module.AbletonGPTControlSurface)
    surface.song = lambda: song
    return surface, song


def test_a_send_can_be_written_and_reads_back():
    """Sends are mixer DeviceParameters, the same kind of object as volume."""

    song = _SendSong([_Send(0.0), _Send(0.0)])
    surface, song = _send_surface(song)

    result = surface._execute(
        "set_track_send", {"track_index": 0, "send_index": 1, "value": 0.42}
    )

    assert song.tracks[0].mixer_device.sends[1].value == 0.42
    assert result["value"] == 0.42
    assert result["return_track"] == "B-Delay"
    assert song.tracks[0].mixer_device.sends[0].value == 0.0


def test_a_send_index_past_the_return_tracks_is_refused():
    """The message has to say how many returns there are, or you guess."""

    song = _SendSong([_Send(0.0), _Send(0.0)])
    surface, song = _send_surface(song)

    try:
        surface._execute(
            "set_track_send", {"track_index": 0, "send_index": 5, "value": 0.3}
        )
    except ValueError as error:
        assert "out of range" in str(error)
        assert "2 return track" in str(error)
    else:
        raise AssertionError("expected the out-of-range send to be refused")


def test_a_locked_send_is_refused_rather_than_silently_ignored():
    song = _SendSong([_Send(0.0, enabled=False)])
    surface, song = _send_surface(song)

    try:
        surface._execute(
            "set_track_send", {"track_index": 0, "send_index": 0, "value": 0.3}
        )
    except ValueError as error:
        assert "locked" in str(error)
    else:
        raise AssertionError("expected a macro-controlled send to be refused")


def test_a_send_outside_the_parameter_range_is_refused():
    song = _SendSong([_Send(0.0)])
    surface, song = _send_surface(song)

    try:
        surface._execute(
            "set_track_send",
            {"track_index": 0, "send_index": 0, "value": 3.0, "normalized": False},
        )
    except ValueError as error:
        assert "out of range" in str(error)
    else:
        raise AssertionError("expected an out-of-range send value to be refused")


def test_creating_a_return_track_reports_where_it_landed():
    song = _SendSong([_Send(0.0), _Send(0.0)])
    surface, song = _send_surface(song)

    result = surface._execute("create_return_track", {"name": "Dub Delay"})

    assert song.created == 1
    assert result["created_index"] == 2
    assert result["name"] == "Dub Delay"
    assert result["return_track_count"] == 3


class _Envelope:
    def __init__(self):
        self.steps = []

    def insert_step(self, start, length, value):
        self.steps.append((start, length, value))

    def value_at_time(self, time):
        # Left-continuous, like Live: a sample on a boundary returns the step
        # that ends there. The writer samples mid-step because of this.
        found = None
        for start, length, value in self.steps:
            if start < time <= start + length:
                found = value
        return 0.0 if found is None else found


class _EnvClip:
    name = "KIHACHI Chords (full)"

    def __init__(self):
        self.envelopes = {}

    def automation_envelope(self, parameter):
        return self.envelopes.get(id(parameter))

    def create_automation_envelope(self, parameter):
        envelope = _Envelope()
        self.envelopes[id(parameter)] = envelope
        return envelope


class _EnvSlot:
    def __init__(self, clip):
        self.has_clip = True
        self.clip = clip


class _EnvTrack:
    name = "KIHACHI Chords"

    def __init__(self, clip, sends):
        self.clip_slots = [_EnvSlot(clip)]
        self.mixer_device = _Mixer(sends)


class _EnvSong:
    def __init__(self, clip, sends):
        self.tracks = [_EnvTrack(clip, sends)]
        self.return_tracks = [_SendTrack("A-Reverb", []), _SendTrack("B-Delay", [])]


def _send_envelope_surface(song):
    module = _load_remote_script()
    surface = module.AbletonGPTControlSurface.__new__(module.AbletonGPTControlSurface)
    surface.song = lambda: song
    return surface


def test_a_send_envelope_is_written_and_verified_mid_step():
    """A dub delay throw is send automation, which device envelopes cannot reach."""

    clip = _EnvClip()
    song = _EnvSong(clip, [_Send(0.0), _Send(0.0)])
    surface = _send_envelope_surface(song)

    result = surface._execute(
        "set_clip_envelope",
        {
            "track_index": 0,
            "clip_index": 0,
            "send_index": 1,
            "steps": [
                {"start": 0.0, "length": 64.0, "value": 0.1},
                {"start": 64.0, "length": 64.0, "value": 0.7},
            ],
        },
    )

    assert result["device"] == "Mixer"
    assert result["parameter"] == "Send B"
    assert result["step_count"] == 2
    assert result["verified_step_count"] == 2
    assert [step["requested"] for step in result["steps"]] == [0.1, 0.7]


def test_a_send_envelope_index_past_the_returns_is_refused():
    clip = _EnvClip()
    song = _EnvSong(clip, [_Send(0.0), _Send(0.0)])
    surface = _send_envelope_surface(song)

    try:
        surface._execute(
            "set_clip_envelope",
            {
                "track_index": 0,
                "clip_index": 0,
                "send_index": 9,
                "steps": [{"start": 0.0, "length": 4.0, "value": 0.5}],
            },
        )
    except ValueError as error:
        assert "out of range" in str(error)
        assert "2 return track" in str(error)
    else:
        raise AssertionError("expected the out-of-range send envelope to be refused")


def test_a_device_envelope_still_reports_its_own_device_and_parameter():
    """The send branch must not change what a device envelope returns."""

    clip = _EnvClip()
    song = _EnvSong(clip, [_Send(0.0)])
    surface = _send_envelope_surface(song)
    parameter = _Send(0.0)
    parameter.name = "Dry Wet"
    device = types.SimpleNamespace(name="Echo")
    surface._parameter = lambda *_args: (parameter, device)

    result = surface._execute(
        "set_clip_envelope",
        {
            "track_index": 0,
            "clip_index": 0,
            "device_index": 1,
            "parameter_index": 52,
            "steps": [{"start": 0.0, "length": 8.0, "value": 0.4}],
        },
    )

    assert result["device"] == "Echo"
    assert result["parameter"] == "Dry Wet"


# --- browser path resolution: folders *and* devices that hold presets ----------

def _browser_surface(root_children):
    """A surface whose browser has one category root with the given children."""
    module = _load_remote_script()
    surface = module.AbletonGPTControlSurface.__new__(module.AbletonGPTControlSurface)
    root = _BrowserItem("audio_effects_root", is_folder=True)
    root.children = list(root_children)
    surface.application = lambda: types.SimpleNamespace(
        browser=types.SimpleNamespace(audio_effects=root)
    )
    return surface


def _device_with_presets(name, preset_names):
    """Live reports a device as is_folder=False even though its presets are children."""
    device = _BrowserItem(name, is_folder=False, is_loadable=True)
    device.children = [_BrowserItem(preset) for preset in preset_names]
    return device


def test_a_device_holding_presets_can_be_descended_even_though_it_is_not_a_folder():
    vocoder = _device_with_presets("Vocoder", ["Chromatic", "Noise Drums"])
    surface = _browser_surface([vocoder])

    node = surface._resolve_browser_node("audio_effects", ["Vocoder"])

    assert node is vocoder
    assert [child.name for child in node.children] == ["Chromatic", "Noise Drums"]


def test_a_childless_non_folder_is_still_not_descendable():
    # A plain preset is a leaf; asking to descend it is a real error.
    surface = _browser_surface([_BrowserItem("Delay", is_folder=False)])

    try:
        surface._resolve_browser_node("audio_effects", ["Delay"])
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("a leaf item must not be descendable")


def test_a_folder_wins_over_a_device_of_the_same_name():
    device = _device_with_presets("Reverb", ["Big Hall"])
    folder = _BrowserItem("Reverb", is_folder=True)
    folder.children = [_BrowserItem("My Reverb")]
    surface = _browser_surface([device, folder])

    assert surface._resolve_browser_node("audio_effects", ["Reverb"]) is folder


def test_folder_descent_is_unchanged():
    inner = _BrowserItem("Bass", is_folder=True)
    inner.children = [_BrowserItem("Sub")]
    outer = _BrowserItem("Presets", is_folder=True)
    outer.children = [inner]
    surface = _browser_surface([outer])

    assert surface._resolve_browser_node("audio_effects", ["Presets", "Bass"]) is inner


def test_an_unreadable_children_query_is_treated_as_not_descendable():
    """``children`` is a live query; a stale item raises rather than returning []."""

    class _Stale(object):
        name = "Ghost"
        is_folder = False

        @property
        def children(self):
            raise RuntimeError("stale browser item")

    surface = _browser_surface([_Stale()])

    try:
        surface._resolve_browser_node("audio_effects", ["Ghost"])
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("an unreadable item must not be descendable")


def test_listing_reports_is_expandable_for_devices_and_folders():
    module = _load_remote_script()
    surface = module.AbletonGPTControlSurface.__new__(module.AbletonGPTControlSurface)
    vocoder = _device_with_presets("Vocoder", ["Chromatic"])
    folder = _BrowserItem("Bass", is_folder=True)
    folder.children = [_BrowserItem("Sub")]
    leaf = _BrowserItem("Delay", is_folder=False)
    root = _BrowserItem("root", is_folder=True)
    root.children = [vocoder, folder, leaf]
    surface.application = lambda: types.SimpleNamespace(
        browser=types.SimpleNamespace(audio_effects=root)
    )

    listing = surface._browse_presets("audio_effects", [], 100)
    expandable = {item["name"]: item["is_expandable"] for item in listing["items"]}

    assert expandable == {"Vocoder": True, "Bass": True, "Delay": False}
    assert listing["read_only"] is True


class _SceneClipSlot:
    def __init__(self, clip):
        self.clip = clip
        self.has_clip = clip is not None


class _SceneClip:
    def __init__(self, name, length):
        self.name = name
        self.length = length
        self.is_audio_clip = False
        self.is_midi_clip = True


class _SceneTrack:
    def __init__(self, name, clip):
        self.name = name
        self.clip_slots = [_SceneClipSlot(clip)]
        self.arrangement_clips = []

    def duplicate_clip_to_arrangement(self, clip, destination_time):
        raise AssertionError("nothing may be copied when the preflight refuses")


class _SceneSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)
        self.scenes = [object()]


def _scene_surface(module, tracks):
    surface = module.AbletonGPTControlSurface.__new__(
        module.AbletonGPTControlSurface
    )
    song = _SceneSong(tracks)
    surface.song = lambda: song
    surface._track = lambda song_, index: song_.tracks[index]
    surface.log_message = lambda *args, **kwargs: None
    return surface


def test_scene_copy_refuses_a_length_the_scene_does_not_have():
    """A copy carries the source clip's length; Live cannot stretch it on the way in.

    So a caller asking for 16 bars from an 8-bar scene has to be refused *before*
    anything is written, not handed a silently shorter clip.
    """
    module = _load_remote_script()
    surface = _scene_surface(
        module,
        [_SceneTrack("Chords", _SceneClip("Chords", 32.0))],
    )

    try:
        surface._execute(
            "copy_scene_to_arrangement",
            {
                "scene_index": 0,
                "destination_time_beats": 96.0,
                "track_indices": None,
                "expected_length_beats": 64.0,
            },
        )
    except ValueError as exc:
        assert "32" in str(exc) and "64" in str(exc)
    else:
        raise AssertionError("a length mismatch must refuse the whole placement")


def test_scene_copy_without_an_expected_length_still_preflights_normally():
    module = _load_remote_script()
    track = _SceneTrack("Chords", _SceneClip("Chords", 32.0))
    surface = _scene_surface(module, [track])
    prepared = []
    surface._prepare_arrangement_copy = lambda ti, tr, clip, dest: prepared.append(ti) or {
        "end_time": dest + clip.length
    }

    try:
        surface._execute(
            "copy_scene_to_arrangement",
            {
                "scene_index": 0,
                "destination_time_beats": 96.0,
                "track_indices": None,
            },
        )
    except AssertionError as exc:
        # _SceneTrack refuses to copy, which is how we know the preflight passed.
        assert "nothing may be copied" in str(exc)
    assert prepared == [0]
