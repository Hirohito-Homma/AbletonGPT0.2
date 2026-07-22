"""Offline audio-track feature extraction (tempo, key, ... ).

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


# Pitch-class names, index 0 == C. Sharps only, matching how Live labels roots.
_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Krumhansl-Schmuckler key profiles: the perceived tonal hierarchy of each scale
# degree, index 0 == tonic. Rotating these to every tonic gives the 24 candidate keys.
_KS_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_KS_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def _pearson(np, a, b) -> float:
    """Pearson correlation of two equal-length vectors; 0 when either is constant."""
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom else 0.0


def estimate_key(
    file_path: str,
    *,
    frame_size: int = 4096,
    min_freq: float = 55.0,
    max_freq: float = 5000.0,
) -> dict[str, Any]:
    """Estimate the musical key of an audio file, offline and deterministically.

    Method: a self-written DFT chromagram (Hann-windowed FFT frames, each magnitude bin
    folded into its nearest pitch class), then Krumhansl-Schmuckler correlation of the
    12-bin chroma against all 24 rotated major/minor key profiles. The best correlation is
    the key. Read-only; never touches Live.
    """
    np = _require_numpy()
    if frame_size < 512 or frame_size & (frame_size - 1):
        raise ValueError("frame_size must be a power of two of at least 512")
    if not 0.0 < min_freq < max_freq:
        raise ValueError("require 0 < min_freq < max_freq")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for key estimation (need at least ~1 second)")
    if signal.size < frame_size:
        raise ValueError("audio is shorter than one analysis frame")

    # Precompute the FFT-bin -> pitch-class map for the usable frequency band.
    freqs = np.fft.rfftfreq(frame_size, 1.0 / sample_rate)
    band = (freqs >= min_freq) & (freqs <= min(max_freq, sample_rate / 2.0))
    if not np.any(band):
        raise ValueError("no FFT bins fall inside the requested frequency band")
    with np.errstate(divide="ignore"):
        midi = 69.0 + 12.0 * np.log2(np.where(freqs > 0.0, freqs, 1.0) / 440.0)
    pitch_class = np.mod(np.rint(midi).astype(int), 12)

    # Hann-windowed overlapping frames, magnitude spectrum summed into 12 pitch classes.
    window = np.hanning(frame_size)
    hop = frame_size // 2
    chroma = np.zeros(12, dtype=np.float64)
    for start in range(0, signal.size - frame_size + 1, hop):
        frame = signal[start : start + frame_size] * window
        magnitude = np.abs(np.fft.rfft(frame))
        chroma += np.bincount(
            pitch_class[band], weights=magnitude[band], minlength=12
        )

    if not np.any(chroma):
        raise ValueError("audio has no tonal content for key estimation")
    chroma_norm = chroma / chroma.sum()

    major = np.asarray(_KS_MAJOR, dtype=np.float64)
    minor = np.asarray(_KS_MINOR, dtype=np.float64)
    scored: list[tuple[float, int, str]] = []
    for tonic in range(12):
        scored.append((_pearson(np, chroma_norm, np.roll(major, tonic)), tonic, "major"))
        scored.append((_pearson(np, chroma_norm, np.roll(minor, tonic)), tonic, "minor"))
    scored.sort(key=lambda item: item[0], reverse=True)

    best_corr, best_tonic, best_mode = scored[0]
    alt_corr, alt_tonic, alt_mode = scored[1]
    tonic_name = _NOTE_NAMES[best_tonic]

    return {
        "read_only": True,
        "file": str(file_path),
        "key": "%s %s" % (tonic_name, best_mode),
        "tonic": tonic_name,
        "mode": best_mode,
        "confidence": round(max(0.0, min(1.0, best_corr)), 4),
        "alternative_key": "%s %s" % (_NOTE_NAMES[alt_tonic], alt_mode),
        "alternative_confidence": round(max(0.0, min(1.0, alt_corr)), 4),
        "chroma": [round(float(value), 4) for value in chroma_norm],
        "sample_rate": sample_rate,
        "duration_seconds": round(signal.size / sample_rate, 3),
        "method": "chroma-krumhansl-schmuckler",
    }
