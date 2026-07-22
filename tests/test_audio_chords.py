"""Tests for offline chord-progression extraction.

Deterministic and self-contained: each test synthesizes a sequence of triads (sine tones
at the chord tones), writes it to a temp WAV with the stdlib ``wave`` module, and checks
the extracted progression. Needs the optional ``audio`` extra (NumPy); skipped cleanly
when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import estimate_chords


_NOTE_INDEX = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
_SR = 22050


def _midi_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _triad(root_midi: int, quality: str, seconds: float):
    third = 3 if quality == "m" else 4
    freqs = [_midi_hz(root_midi), _midi_hz(root_midi + third), _midi_hz(root_midi + 7)]
    t = np.arange(int(_SR * seconds))
    tone = sum(np.sin(2 * np.pi * f * t / _SR) for f in freqs) / len(freqs)
    envelope = np.minimum(1.0, np.minimum(t, t[::-1]) / (0.01 * _SR))
    return tone * envelope


def _progression(chords, seconds: float):
    parts = []
    for name in chords:
        quality = "m" if name.endswith("m") else ""
        root = name[:-1] if quality else name
        parts.append(_triad(48 + _NOTE_INDEX[root], quality, seconds))
    return np.concatenate(parts)


def _write_wav(path: Path, signal) -> Path:
    data = (np.clip(signal * 0.5, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def test_extracts_major_progression(tmp_path: Path):
    wav = _write_wav(tmp_path / "prog.wav", _progression(["C", "F", "G", "C"], 1.5))

    result = estimate_chords(str(wav))

    assert result["read_only"] is True
    assert result["progression"] == ["C", "F", "G", "C"]
    assert all(0.0 <= seg["confidence"] <= 1.0 for seg in result["chords"])


def test_distinguishes_minor_chords(tmp_path: Path):
    wav = _write_wav(tmp_path / "minor.wav", _progression(["A", "Am", "Dm", "E"], 1.5))

    result = estimate_chords(str(wav))

    assert result["progression"] == ["A", "Am", "Dm", "E"]


def test_segments_span_the_audio_without_gaps(tmp_path: Path):
    wav = _write_wav(tmp_path / "prog.wav", _progression(["C", "G"], 1.5))

    result = estimate_chords(str(wav))
    segments = result["chords"]

    assert segments[0]["start_seconds"] == 0.0
    for earlier, later in zip(segments, segments[1:]):
        assert earlier["end_seconds"] == later["start_seconds"]
    assert segments[-1]["end_seconds"] == pytest.approx(result["duration_seconds"], abs=0.05)


def test_labels_silence_as_no_chord(tmp_path: Path):
    silence = np.zeros(int(_SR * 1.2), dtype=np.float64)
    signal = np.concatenate([_triad(60, "", 1.2), silence, _triad(60, "", 1.2)])
    wav = _write_wav(tmp_path / "gap.wav", signal)

    result = estimate_chords(str(wav))

    assert any(seg["chord"] == "N" for seg in result["chords"])
    assert result["progression"] == ["C", "C"]


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "prog.wav", _progression(["C", "F"], 1.5))

    assert estimate_chords(str(wav)) == estimate_chords(str(wav))


def test_rejects_bad_window_seconds(tmp_path: Path):
    wav = _write_wav(tmp_path / "prog.wav", _progression(["C"], 2.0))

    with pytest.raises(ValueError):
        estimate_chords(str(wav), window_seconds=0.0)
