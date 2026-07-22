"""Tests for stereo-field analysis (width / phase correlation / balance).

Deterministic and self-contained: each test writes a stereo (or mono) WAV with known channel
relationships via the stdlib ``wave`` module and checks the measured image. Needs the
optional ``audio`` extra (NumPy); skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import analyze_stereo_field


_SR = 44100


def _write_wav(path: Path, channels) -> Path:
    # channels: list of 1-D float arrays (1 = mono, 2 = stereo).
    stacked = np.stack(channels, axis=1)  # (frames, channels)
    data = (np.clip(stacked, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(len(channels))
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def _tone(freq: float, seconds: float, amp: float = 0.5):
    t = np.arange(int(_SR * seconds))
    return amp * np.sin(2 * np.pi * freq * t / _SR)


def test_mono_file_is_fully_centred(tmp_path: Path):
    wav = _write_wav(tmp_path / "mono.wav", [_tone(440.0, 2.0)])

    result = analyze_stereo_field(str(wav))

    assert result["is_stereo"] is False
    assert result["width_side_ratio"] == 0.0
    assert result["correlation"] == 1.0


def test_identical_channels_read_as_centred(tmp_path: Path):
    tone = _tone(440.0, 2.0)
    wav = _write_wav(tmp_path / "dual_mono.wav", [tone, tone])

    result = analyze_stereo_field(str(wav))

    assert result["is_stereo"] is True
    assert result["width_side_ratio"] == pytest.approx(0.0, abs=1e-6)
    assert result["correlation"] == pytest.approx(1.0, abs=1e-4)


def test_anti_phase_is_fully_wide_and_negatively_correlated(tmp_path: Path):
    tone = _tone(440.0, 2.0)
    wav = _write_wav(tmp_path / "antiphase.wav", [tone, -tone])

    result = analyze_stereo_field(str(wav))

    assert result["width_side_ratio"] == pytest.approx(1.0, abs=1e-6)
    assert result["correlation"] == pytest.approx(-1.0, abs=1e-4)


def test_independent_channels_are_roughly_decorrelated(tmp_path: Path):
    rng = np.random.default_rng(0)
    left = rng.uniform(-0.5, 0.5, int(_SR * 2.0))
    right = rng.uniform(-0.5, 0.5, int(_SR * 2.0))
    wav = _write_wav(tmp_path / "noise.wav", [left, right])

    result = analyze_stereo_field(str(wav))

    assert abs(result["correlation"]) < 0.1
    assert result["width_side_ratio"] == pytest.approx(0.5, abs=0.05)


def test_louder_left_channel_reports_positive_balance(tmp_path: Path):
    wav = _write_wav(tmp_path / "balance.wav", [_tone(440.0, 2.0, amp=0.8), _tone(440.0, 2.0, amp=0.4)])

    result = analyze_stereo_field(str(wav))

    assert result["balance_db"] > 3.0  # left is ~6 dB louder


def test_is_deterministic(tmp_path: Path):
    tone = _tone(440.0, 2.0)
    wav = _write_wav(tmp_path / "s.wav", [tone, 0.5 * tone])

    assert analyze_stereo_field(str(wav)) == analyze_stereo_field(str(wav))


def test_rejects_too_short_audio(tmp_path: Path):
    tone = _tone(440.0, 0.3)
    wav = _write_wav(tmp_path / "short.wav", [tone, tone])

    with pytest.raises(ValueError):
        analyze_stereo_field(str(wav))
