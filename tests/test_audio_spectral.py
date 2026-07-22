"""Tests for offline spectral-feature extraction.

Deterministic and self-contained: each test synthesizes a signal with known spectral
character (a low sine, a high sine, or white noise), writes it to a temp WAV with the
stdlib ``wave`` module, and checks the summarised features. Needs the optional ``audio``
extra (NumPy); skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import extract_spectral_features


_SR = 22050


def _sine(freq: float, seconds: float):
    t = np.arange(int(_SR * seconds))
    return np.sin(2 * np.pi * freq * t / _SR)


def _noise(seconds: float):
    rng = np.random.default_rng(0)
    return rng.uniform(-1.0, 1.0, int(_SR * seconds))


def _write_wav(path: Path, signal) -> Path:
    data = (np.clip(signal * 0.5, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def test_features_shape_and_keys(tmp_path: Path):
    wav = _write_wav(tmp_path / "tone.wav", _sine(440.0, 2.0))

    result = extract_spectral_features(str(wav))

    assert result["read_only"] is True
    assert set(result["features"]) == {
        "spectral_centroid_hz",
        "spectral_bandwidth_hz",
        "spectral_rolloff_hz",
        "spectral_flatness",
        "zero_crossing_rate",
        "rms",
    }
    for stats in result["features"].values():
        assert set(stats) == {"mean", "std", "min", "max"}
    assert result["frames_analyzed"] > 0


def test_centroid_tracks_pitch_height(tmp_path: Path):
    low = extract_spectral_features(str(_write_wav(tmp_path / "low.wav", _sine(220.0, 2.0))))
    high = extract_spectral_features(str(_write_wav(tmp_path / "high.wav", _sine(3520.0, 2.0))))

    low_centroid = low["features"]["spectral_centroid_hz"]["mean"]
    high_centroid = high["features"]["spectral_centroid_hz"]["mean"]
    assert high_centroid > low_centroid
    # A ~220 Hz sine sits low; a ~3520 Hz sine sits high.
    assert low_centroid < 1000.0
    assert high_centroid > 2500.0


def test_noise_is_flatter_and_crosses_more_than_a_tone(tmp_path: Path):
    tone = extract_spectral_features(str(_write_wav(tmp_path / "tone.wav", _sine(440.0, 2.0))))
    noise = extract_spectral_features(str(_write_wav(tmp_path / "noise.wav", _noise(2.0))))

    assert (
        noise["features"]["spectral_flatness"]["mean"]
        > tone["features"]["spectral_flatness"]["mean"]
    )
    assert (
        noise["features"]["zero_crossing_rate"]["mean"]
        > tone["features"]["zero_crossing_rate"]["mean"]
    )


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "tone.wav", _sine(440.0, 2.0))

    assert extract_spectral_features(str(wav)) == extract_spectral_features(str(wav))


def test_rejects_silence(tmp_path: Path):
    wav = _write_wav(tmp_path / "silent.wav", np.zeros(int(_SR * 2.0), dtype=np.float64))

    with pytest.raises(ValueError):
        extract_spectral_features(str(wav))


def test_rejects_bad_rolloff(tmp_path: Path):
    wav = _write_wav(tmp_path / "tone.wav", _sine(440.0, 2.0))

    with pytest.raises(ValueError):
        extract_spectral_features(str(wav), rolloff_percent=1.5)
