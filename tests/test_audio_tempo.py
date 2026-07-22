"""Tests for offline tempo estimation.

Deterministic and self-contained: each test synthesizes a click track at a known BPM,
writes it to a temp WAV with the stdlib ``wave`` module, and checks the estimate. Needs the
optional ``audio`` extra (NumPy); skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import estimate_tempo


def _click_track(sample_rate: int, bpm: float, seconds: float):
    total = int(sample_rate * seconds)
    signal = np.zeros(total, dtype=np.float64)
    period = int(round(sample_rate * 60.0 / bpm))
    burst_len = int(sample_rate * 0.05)
    t = np.arange(burst_len)
    burst = np.sin(2 * np.pi * 1000.0 * t / sample_rate) * np.exp(-t / (0.01 * sample_rate))
    for start in range(0, total - burst_len, period):
        signal[start : start + burst_len] += burst
    return signal


def _write_wav(path: Path, signal, sample_rate: int) -> Path:
    pcm = np.clip(signal * 0.5, -1.0, 1.0)
    data = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data.tobytes())
    return path


@pytest.mark.parametrize("bpm", [100.0, 120.0, 140.0])
def test_estimates_known_click_tempo(tmp_path: Path, bpm: float):
    wav = _write_wav(tmp_path / "click.wav", _click_track(22050, bpm, 8.0), 22050)

    result = estimate_tempo(str(wav))

    assert result["read_only"] is True
    assert abs(result["tempo_bpm"] - bpm) <= 2.0
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["sample_rate"] == 22050


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "click.wav", _click_track(22050, 128.0, 6.0), 22050)

    assert estimate_tempo(str(wav)) == estimate_tempo(str(wav))


def test_rejects_too_short_audio(tmp_path: Path):
    wav = _write_wav(tmp_path / "short.wav", _click_track(22050, 120.0, 0.3), 22050)

    with pytest.raises(ValueError):
        estimate_tempo(str(wav))


def test_rejects_bad_bpm_range(tmp_path: Path):
    wav = _write_wav(tmp_path / "click.wav", _click_track(22050, 120.0, 4.0), 22050)

    with pytest.raises(ValueError):
        estimate_tempo(str(wav), min_bpm=200.0, max_bpm=100.0)
