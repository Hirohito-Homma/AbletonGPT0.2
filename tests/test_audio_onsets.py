"""Tests for offline onset/transient detection.

Deterministic and self-contained: each test synthesizes tone bursts at known times, writes
them to a temp WAV with the stdlib ``wave`` module, and checks the detected onset times.
Needs the optional ``audio`` extra (NumPy); skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import detect_onsets


_SR = 22050


def _bursts(times, seconds: float, freq: float = 440.0):
    total = int(_SR * seconds)
    signal = np.zeros(total, dtype=np.float64)
    burst_len = int(_SR * 0.08)
    t = np.arange(burst_len)
    burst = np.sin(2 * np.pi * freq * t / _SR) * np.exp(-t / (0.02 * _SR))
    for onset_time in times:
        start = int(onset_time * _SR)
        end = min(total, start + burst_len)
        signal[start:end] += burst[: end - start]
    return signal


def _write_wav(path: Path, signal) -> Path:
    data = (np.clip(signal * 0.5, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def _closest(times, target):
    return min(times, key=lambda value: abs(value - target))


def test_detects_bursts_at_known_times(tmp_path: Path):
    expected = [0.5, 1.0, 1.5, 2.0, 2.5]
    wav = _write_wav(tmp_path / "bursts.wav", _bursts(expected, 3.0))

    result = detect_onsets(str(wav))

    assert result["read_only"] is True
    assert result["onset_count"] == len(expected)
    for target in expected:
        assert abs(_closest(result["onset_times"], target) - target) <= 0.03
    assert all(0.0 <= onset["strength"] <= 1.0 for onset in result["onsets"])


def test_onset_times_are_sorted(tmp_path: Path):
    wav = _write_wav(tmp_path / "bursts.wav", _bursts([0.4, 0.9, 1.7], 2.5))

    times = detect_onsets(str(wav))["onset_times"]

    assert times == sorted(times)


def test_min_gap_merges_close_peaks(tmp_path: Path):
    # A single burst must not yield two onsets from its attack transient.
    wav = _write_wav(tmp_path / "one.wav", _bursts([1.0], 2.0))

    result = detect_onsets(str(wav))

    assert result["onset_count"] == 1


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "bursts.wav", _bursts([0.5, 1.2], 2.0))

    assert detect_onsets(str(wav)) == detect_onsets(str(wav))


def test_rejects_silence(tmp_path: Path):
    wav = _write_wav(tmp_path / "silent.wav", np.zeros(int(_SR * 2.0), dtype=np.float64))

    with pytest.raises(ValueError):
        detect_onsets(str(wav))


def test_rejects_bad_delta(tmp_path: Path):
    wav = _write_wav(tmp_path / "bursts.wav", _bursts([0.5, 1.0], 2.0))

    with pytest.raises(ValueError):
        detect_onsets(str(wav), delta=1.5)
