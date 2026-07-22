"""Tests for level-independent tonal band-balance extraction.

Deterministic and self-contained: each test synthesizes tones in known bands, writes them to
a temp WAV with the stdlib ``wave`` module, and checks the band fractions. Needs the optional
``audio`` extra (NumPy); skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import extract_spectral_bands


_SR = 44100


def _tone(freq: float, seconds: float, amp: float = 0.5):
    t = np.arange(int(_SR * seconds))
    return amp * np.sin(2 * np.pi * freq * t / _SR)


def _write_wav(path: Path, signal) -> Path:
    data = (np.clip(signal, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def test_bands_sum_to_one_and_have_expected_names(tmp_path: Path):
    wav = _write_wav(tmp_path / "tone.wav", _tone(1000.0, 2.0))

    result = extract_spectral_bands(str(wav))

    assert result["read_only"] is True
    names = [band["name"] for band in result["bands"]]
    assert names == ["low", "low_mid", "mid", "high_mid", "high"]
    assert sum(result["band_fractions"].values()) == pytest.approx(1.0, abs=1e-4)


def test_low_tone_concentrates_in_low_band(tmp_path: Path):
    wav = _write_wav(tmp_path / "low.wav", _tone(80.0, 2.0))

    fractions = extract_spectral_bands(str(wav))["band_fractions"]

    assert fractions["low"] > 0.8
    assert fractions["low"] == max(fractions.values())


def test_high_tone_concentrates_in_high_band(tmp_path: Path):
    wav = _write_wav(tmp_path / "high.wav", _tone(9000.0, 2.0))

    fractions = extract_spectral_bands(str(wav))["band_fractions"]

    assert fractions["high"] > 0.8


def test_is_level_independent(tmp_path: Path):
    quiet = _write_wav(tmp_path / "quiet.wav", _tone(1000.0, 2.0, amp=0.1))
    loud = _write_wav(tmp_path / "loud.wav", _tone(1000.0, 2.0, amp=0.9))

    quiet_fractions = extract_spectral_bands(str(quiet))["band_fractions"]
    loud_fractions = extract_spectral_bands(str(loud))["band_fractions"]

    for name in quiet_fractions:
        assert quiet_fractions[name] == pytest.approx(loud_fractions[name], abs=1e-3)


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "tone.wav", _tone(1000.0, 2.0))

    assert extract_spectral_bands(str(wav)) == extract_spectral_bands(str(wav))


def test_rejects_silence(tmp_path: Path):
    wav = _write_wav(tmp_path / "silent.wav", np.zeros(int(_SR * 2.0), dtype=np.float64))

    with pytest.raises(ValueError):
        extract_spectral_bands(str(wav))
