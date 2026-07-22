"""Tests for offline key estimation.

Deterministic and self-contained: each test synthesizes tonal material (a scale or a
diatonic chord progression) in a known key, writes it to a temp WAV with the stdlib
``wave`` module, and checks the estimate. Needs the optional ``audio`` extra (NumPy);
skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import estimate_key


_NOTE_INDEX = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}

_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
_NATURAL_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)


def _midi_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _tone(sample_rate: int, freqs, seconds: float):
    t = np.arange(int(sample_rate * seconds))
    tone = np.zeros(t.size, dtype=np.float64)
    for freq in freqs:
        tone += np.sin(2 * np.pi * freq * t / sample_rate)
    envelope = np.minimum(1.0, np.minimum(t, t[::-1]) / (0.01 * sample_rate))
    return tone / len(freqs) * envelope


def _scale(sample_rate: int, tonic_midi: int, steps, seconds_per_note: float):
    notes = [_tone(sample_rate, [_midi_hz(tonic_midi + step)], seconds_per_note) for step in steps]
    notes.append(_tone(sample_rate, [_midi_hz(tonic_midi + 12)], seconds_per_note))
    return np.concatenate(notes)


def _triad(sample_rate: int, root_midi: int, thirds, seconds: float):
    freqs = [_midi_hz(root_midi), _midi_hz(root_midi + thirds[0]), _midi_hz(root_midi + 7)]
    return _tone(sample_rate, freqs, seconds)


def _write_wav(path: Path, signal, sample_rate: int) -> Path:
    pcm = np.clip(signal * 0.5, -1.0, 1.0)
    data = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data.tobytes())
    return path


@pytest.mark.parametrize("tonic", ["C", "G", "F", "A"])
def test_estimates_major_scale_key(tmp_path: Path, tonic: str):
    tonic_midi = 60 + _NOTE_INDEX[tonic]
    signal = _scale(22050, tonic_midi, _MAJOR_STEPS, 0.35)
    wav = _write_wav(tmp_path / "scale.wav", signal, 22050)

    result = estimate_key(str(wav))

    assert result["read_only"] is True
    assert result["tonic"] == tonic
    assert result["mode"] == "major"
    assert result["key"] == "%s major" % tonic
    assert 0.0 <= result["confidence"] <= 1.0
    assert len(result["chroma"]) == 12


def test_estimates_minor_progression_key(tmp_path: Path):
    # A natural-minor scale plus its i-iv-v triads should resolve to A minor.
    tonic_midi = 57  # A3
    parts = [_scale(22050, tonic_midi, _NATURAL_MINOR_STEPS, 0.3)]
    for root in (tonic_midi, tonic_midi + 5, tonic_midi + 7):  # i, iv, v roots
        parts.append(_triad(22050, root, (3,), 0.6))
    wav = _write_wav(tmp_path / "minor.wav", np.concatenate(parts), 22050)

    result = estimate_key(str(wav))

    assert result["tonic"] == "A"
    assert result["mode"] == "minor"


def test_is_deterministic(tmp_path: Path):
    signal = _scale(22050, 60, _MAJOR_STEPS, 0.3)
    wav = _write_wav(tmp_path / "scale.wav", signal, 22050)

    assert estimate_key(str(wav)) == estimate_key(str(wav))


def test_rejects_too_short_audio(tmp_path: Path):
    signal = _tone(22050, [_midi_hz(60)], 0.3)
    wav = _write_wav(tmp_path / "short.wav", signal, 22050)

    with pytest.raises(ValueError):
        estimate_key(str(wav))


def test_rejects_bad_frame_size(tmp_path: Path):
    signal = _scale(22050, 60, _MAJOR_STEPS, 0.3)
    wav = _write_wav(tmp_path / "scale.wav", signal, 22050)

    with pytest.raises(ValueError):
        estimate_key(str(wav), frame_size=3000)
