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
