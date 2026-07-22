"""Tests for offline beat-grid tracking.

Deterministic and self-contained: each test synthesizes a click track at a known BPM and
phase, writes it to a temp WAV with the stdlib ``wave`` module, and checks the tracked beat
grid. Needs the optional ``audio`` extra (NumPy); skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import track_beats


_SR = 22050


def _click_track(bpm: float, seconds: float, offset: float = 0.0):
    total = int(_SR * seconds)
    signal = np.zeros(total, dtype=np.float64)
    period = 60.0 / bpm
    burst_len = int(_SR * 0.05)
    t = np.arange(burst_len)
    burst = np.sin(2 * np.pi * 1000.0 * t / _SR) * np.exp(-t / (0.01 * _SR))
    tick = offset
    while int(tick * _SR) + burst_len < total:
        start = int(tick * _SR)
        signal[start : start + burst_len] += burst
        tick += period
    return signal


def _write_wav(path: Path, signal) -> Path:
    data = (np.clip(signal * 0.5, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def test_tracks_tempo_and_beat_spacing(tmp_path: Path):
    wav = _write_wav(tmp_path / "click.wav", _click_track(120.0, 8.0))

    result = track_beats(str(wav))

    assert result["read_only"] is True
    assert abs(result["tempo_bpm"] - 120.0) <= 2.0
    assert abs(result["beat_period_seconds"] - 0.5) <= 0.02
    # Consecutive beats are one period apart.
    times = result["beat_times"]
    assert len(times) >= 12
    diffs = np.diff(times)
    assert np.allclose(diffs, result["beat_period_seconds"], atol=0.03)


def test_beats_align_to_click_phase(tmp_path: Path):
    # Clicks start at 0.25 s; the grid phase should lock onto them.
    wav = _write_wav(tmp_path / "click.wav", _click_track(120.0, 8.0, offset=0.25))

    result = track_beats(str(wav))
    period = result["beat_period_seconds"]
    # Every beat should fall close to a click at 0.25 + k*0.5.
    for time in result["beat_times"]:
        phase = (time - 0.25) % period
        assert min(phase, period - phase) <= 0.04


def test_bar_starts_group_by_beats_per_bar(tmp_path: Path):
    wav = _write_wav(tmp_path / "click.wav", _click_track(120.0, 8.0))

    result = track_beats(str(wav), beats_per_bar=4)

    assert result["bar_start_times"] == result["beat_times"][::4]
    assert result["beats_per_bar"] == 4


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "click.wav", _click_track(128.0, 6.0))

    assert track_beats(str(wav)) == track_beats(str(wav))


def test_rejects_silence(tmp_path: Path):
    wav = _write_wav(tmp_path / "silent.wav", np.zeros(int(_SR * 2.0), dtype=np.float64))

    with pytest.raises(ValueError):
        track_beats(str(wav))


def test_rejects_bad_beats_per_bar(tmp_path: Path):
    wav = _write_wav(tmp_path / "click.wav", _click_track(120.0, 4.0))

    with pytest.raises(ValueError):
        track_beats(str(wav), beats_per_bar=0)
