"""Tests for offline monophonic melody extraction.

Deterministic and self-contained: each test synthesizes a single-line melody (one sine
tone at a time), writes it to a temp WAV with the stdlib ``wave`` module, and checks the
extracted note sequence. Needs the optional ``audio`` extra (NumPy); skipped cleanly when
it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import extract_melody


_SR = 22050


def _midi_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _note(midi: int, seconds: float):
    t = np.arange(int(_SR * seconds))
    tone = np.sin(2 * np.pi * _midi_hz(midi) * t / _SR)
    envelope = np.minimum(1.0, np.minimum(t, t[::-1]) / (0.01 * _SR))
    return tone * envelope


def _melody(midis, seconds: float):
    return np.concatenate([_note(midi, seconds) for midi in midis])


def _write_wav(path: Path, signal) -> Path:
    data = (np.clip(signal * 0.5, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def test_extracts_ascending_line(tmp_path: Path):
    # C4, E4, G4, C5.
    wav = _write_wav(tmp_path / "line.wav", _melody([60, 64, 67, 72], 0.6))

    result = extract_melody(str(wav))

    assert result["read_only"] is True
    assert result["note_names"] == ["C4", "E4", "G4", "C5"]
    assert all(note["midi"] in (60, 64, 67, 72) for note in result["notes"])
    assert all(0.0 <= note["confidence"] <= 1.0 for note in result["notes"])


def test_notes_are_time_ordered_and_within_duration(tmp_path: Path):
    wav = _write_wav(tmp_path / "line.wav", _melody([57, 60, 64], 0.6))

    result = extract_melody(str(wav))
    notes = result["notes"]

    assert notes[0]["start_seconds"] >= 0.0
    for earlier, later in zip(notes, notes[1:]):
        assert earlier["start_seconds"] <= later["start_seconds"]
    assert notes[-1]["end_seconds"] <= result["duration_seconds"] + 1e-6


def test_silence_breaks_the_line(tmp_path: Path):
    silence = np.zeros(int(_SR * 0.6), dtype=np.float64)
    signal = np.concatenate([_note(60, 0.6), silence, _note(67, 0.6)])
    wav = _write_wav(tmp_path / "gap.wav", signal)

    result = extract_melody(str(wav))

    assert result["note_names"] == ["C4", "G4"]


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "line.wav", _melody([60, 62], 0.7))

    assert extract_melody(str(wav)) == extract_melody(str(wav))


def test_rejects_too_short_audio(tmp_path: Path):
    wav = _write_wav(tmp_path / "short.wav", _note(60, 0.3))

    with pytest.raises(ValueError):
        extract_melody(str(wav))


def test_rejects_bad_f0_range(tmp_path: Path):
    wav = _write_wav(tmp_path / "line.wav", _melody([60, 64], 0.7))

    with pytest.raises(ValueError):
        extract_melody(str(wav), min_f0=800.0, max_f0=200.0)
