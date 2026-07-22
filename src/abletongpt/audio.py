"""Offline audio-track feature extraction (tempo, ... ).

Like :mod:`abletongpt.loudness`, this reads a WAV/AIFF file and never writes. Unlike the
rest of the package it needs an optional dependency, NumPy, for the DSP -- install it with
``pip install abletongpt[audio]``. NumPy is imported lazily so importing this module (and
the base install) stays dependency-free; only calling an extraction function needs it.

The extractors are deterministic: the same file and settings always give the same result.
They read the audio through :mod:`abletongpt.loudness`'s reader, so every format that
loudness analysis supports works here too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .loudness import _open_audio


class AudioDependencyError(RuntimeError):
    """Raised when the optional ``audio`` extra (NumPy) is not installed."""


def _require_numpy():
    """Import NumPy or raise a clear, actionable error."""
    try:
        import numpy  # noqa: PLC0415 - intentionally lazy so the base install is dep-free
    except ModuleNotFoundError as exc:
        raise AudioDependencyError(
            "audio extraction needs NumPy; install it with: pip install abletongpt[audio]"
        ) from exc
    return numpy


def _read_mono(path: Path):
    """Return ``(mono_signal, sample_rate)`` as a float64 NumPy array averaged over channels."""
    np = _require_numpy()
    with _open_audio(path) as stream:
        sample_rate = int(stream.sample_rate)
        channels = int(stream.channels)
        blocks = []
        for chunk in stream.frames(chunk_frames=65536):
            block = np.asarray(chunk, dtype=np.float64)
            if channels > 1:
                usable = block[: (block.size // channels) * channels]
                block = usable.reshape(-1, channels).mean(axis=1)
            blocks.append(block)
    signal = np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float64)
    return signal, sample_rate


def estimate_tempo(
    file_path: str,
    *,
    min_bpm: float = 60.0,
    max_bpm: float = 200.0,
    hop: int = 256,
) -> dict[str, Any]:
    """Estimate the tempo (BPM) of an audio file, offline and deterministically.

    Method: a per-hop energy envelope, half-wave-rectified onset strength (positive log-energy
    increases), then FFT autocorrelation whose strongest peak inside the ``[min_bpm, max_bpm]``
    lag window gives the beat period. Read-only; never touches Live.
    """
    np = _require_numpy()
    if not 20.0 <= min_bpm < max_bpm <= 400.0:
        raise ValueError("require 20 <= min_bpm < max_bpm <= 400")
    if hop < 64:
        raise ValueError("hop must be at least 64 samples")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for tempo estimation (need at least ~1 second)")

    # Per-hop energy -> onset strength (positive change in log-energy).
    usable = signal[: (signal.size // hop) * hop]
    energy = (usable.reshape(-1, hop) ** 2).sum(axis=1)
    onset = np.diff(np.log1p(energy))
    onset = np.maximum(onset, 0.0)
    onset = onset - onset.mean()
    if not np.any(onset):
        raise ValueError("audio has no detectable onsets for tempo estimation")

    # FFT autocorrelation of the onset envelope.
    n = onset.size
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(onset, size)
    autocorr = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]

    fps = sample_rate / hop
    min_lag = max(1, int(round(fps * 60.0 / max_bpm)))
    max_lag = min(n - 1, int(round(fps * 60.0 / min_bpm)))
    if min_lag >= max_lag:
        raise ValueError("audio is too short for the requested BPM range")

    # Smooth the autocorrelation with a small boxcar so a fundamental peak split across
    # adjacent lags (a non-integer beat period in frames) is not beaten by its cleanly
    # aligned 2x sub-harmonic. Then weight by a log-normal tempo prior centred on 120 BPM
    # to resolve the remaining octave ambiguity toward the musically likely range.
    smoothed = np.convolve(autocorr, np.ones(3) / 3.0, mode="same")
    lags = np.arange(min_lag, max_lag + 1)
    candidate_bpms = 60.0 * fps / lags
    prior = np.exp(-0.5 * (np.log2(candidate_bpms / 120.0) / 0.8) ** 2)
    best_lag = int(lags[int(np.argmax(smoothed[min_lag : max_lag + 1] * prior))])

    # Recenter on the true raw peak near the smoothed choice, so the parabolic step below
    # interpolates around an actual maximum (a split peak can leave the smoothed argmax on
    # the lower of the two adjacent lags).
    lo = max(min_lag, best_lag - 2)
    hi = min(max_lag, best_lag + 2)
    best_lag = lo + int(np.argmax(autocorr[lo : hi + 1]))

    # Parabolic interpolation on the raw autocorrelation for sub-lag BPM accuracy.
    refined_lag = float(best_lag)
    if 0 < best_lag < n - 1:
        a, b, c = autocorr[best_lag - 1], autocorr[best_lag], autocorr[best_lag + 1]
        denom = a - 2.0 * b + c
        if denom != 0:
            refined_lag = best_lag + max(-1.0, min(1.0, 0.5 * (a - c) / denom))

    tempo = 60.0 * fps / refined_lag
    confidence = float(autocorr[best_lag] / (autocorr[0] + 1e-12))

    return {
        "read_only": True,
        "file": str(file_path),
        "tempo_bpm": round(float(tempo), 2),
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "sample_rate": sample_rate,
        "duration_seconds": round(signal.size / sample_rate, 3),
        "bpm_range": [min_bpm, max_bpm],
        "method": "onset-autocorrelation",
    }
