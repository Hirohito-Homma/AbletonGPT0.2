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

import math
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


def _read_channels(path: Path):
    """Return ``(samples, sample_rate, channels)`` with ``samples`` shaped ``(frames, channels)``.

    Unlike :func:`_read_mono` this keeps the channels separate, for stereo-field analysis.
    """
    np = _require_numpy()
    with _open_audio(path) as stream:
        sample_rate = int(stream.sample_rate)
        channels = int(stream.channels)
        blocks = []
        for chunk in stream.frames(chunk_frames=65536):
            block = np.asarray(chunk, dtype=np.float64)
            usable = block[: (block.size // channels) * channels]
            blocks.append(usable.reshape(-1, channels))
    samples = np.concatenate(blocks) if blocks else np.zeros((0, channels), dtype=np.float64)
    return samples, sample_rate, channels


def _onset_strength(np, signal, hop: int):
    """Per-hop onset-strength envelope: the half-wave-rectified rise in log energy.

    One value per ``hop``-sample frame. Positive where energy increases (a note/transient
    starting), zero elsewhere. Shared by :func:`estimate_tempo` (which centres it for
    autocorrelation) and :func:`detect_onsets` (which peak-picks it).
    """
    usable = signal[: (signal.size // hop) * hop]
    energy = (usable.reshape(-1, hop) ** 2).sum(axis=1)
    onset = np.diff(np.log1p(energy))
    return np.maximum(onset, 0.0)


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

    # Per-hop onset strength, then centre it for the autocorrelation below.
    onset = _onset_strength(np, signal, hop)
    onset = onset - onset.mean()
    if not np.any(onset):
        raise ValueError("audio has no detectable onsets for tempo estimation")

    tempo, confidence = _tempo_from_onset(np, onset, sample_rate / hop, min_bpm, max_bpm)

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


def _tempo_from_onset(np, onset, fps: float, min_bpm: float, max_bpm: float):
    """Return ``(tempo_bpm, confidence)`` from a centred onset envelope via autocorrelation.

    Shared by :func:`estimate_tempo` and :func:`track_beats` so both agree on the tempo.
    """
    n = onset.size
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(onset, size)
    autocorr = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]

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
    return tempo, confidence


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


def _chromagram(np, file_path: str, frame_size: int, min_freq: float, max_freq: float):
    """Return ``(chroma_frames, hop, sample_rate, signal_size)`` for a file.

    ``chroma_frames`` is an ``(n_frames, 12)`` float array: one 12-bin pitch-class energy
    vector per Hann-windowed FFT frame, each magnitude bin folded into its nearest pitch
    class. Shared by :func:`estimate_key` (which sums over time) and :func:`estimate_chords`
    (which tracks the chroma over time). Validates its DSP arguments and the audio length.
    """
    if frame_size < 512 or frame_size & (frame_size - 1):
        raise ValueError("frame_size must be a power of two of at least 512")
    if not 0.0 < min_freq < max_freq:
        raise ValueError("require 0 < min_freq < max_freq")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for analysis (need at least ~1 second)")
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
    band_pc = pitch_class[band]

    window = np.hanning(frame_size)
    hop = frame_size // 2
    rows = []
    for start in range(0, signal.size - frame_size + 1, hop):
        frame = signal[start : start + frame_size] * window
        magnitude = np.abs(np.fft.rfft(frame))
        rows.append(np.bincount(band_pc, weights=magnitude[band], minlength=12))
    chroma_frames = np.asarray(rows, dtype=np.float64) if rows else np.zeros((0, 12))
    return chroma_frames, hop, sample_rate, int(signal.size)


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
    chroma_frames, _hop, sample_rate, signal_size = _chromagram(
        np, file_path, frame_size, min_freq, max_freq
    )

    chroma = chroma_frames.sum(axis=0)
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
        "duration_seconds": round(signal_size / sample_rate, 3),
        "method": "chroma-krumhansl-schmuckler",
    }


# Chord templates: interval sets relative to the root, index 0 == root. Kept to the two
# common triad qualities so the label set stays small and the matcher stays robust.
_CHORD_QUALITIES = (("", (0, 4, 7)), ("m", (0, 3, 7)))


def _chord_templates(np):
    """Return ``[(label, unit_template_vector)]`` for every root x quality triad."""
    templates = []
    for root in range(12):
        for suffix, intervals in _CHORD_QUALITIES:
            vector = np.zeros(12, dtype=np.float64)
            for interval in intervals:
                vector[(root + interval) % 12] = 1.0
            templates.append(("%s%s" % (_NOTE_NAMES[root], suffix), vector))
    return templates


def estimate_chords(
    file_path: str,
    *,
    frame_size: int = 4096,
    window_seconds: float = 0.5,
    min_freq: float = 55.0,
    max_freq: float = 5000.0,
    silence_ratio: float = 0.05,
) -> dict[str, Any]:
    """Extract a chord progression from an audio file, offline and deterministically.

    Method: the shared DFT chromagram is averaged into ``window_seconds`` windows; each
    window's chroma is matched (Pearson correlation) against the 24 major/minor triad
    templates, and consecutive equal labels are merged into timed segments. Windows quieter
    than ``silence_ratio`` of the loudest window are labelled ``"N"`` (no chord). This is a
    lightweight triad recogniser, not a full functional-harmony analysis. Read-only.
    """
    np = _require_numpy()
    if not 0.05 <= window_seconds <= 10.0:
        raise ValueError("window_seconds must be between 0.05 and 10")
    if not 0.0 <= silence_ratio < 1.0:
        raise ValueError("silence_ratio must be in [0, 1)")

    chroma_frames, hop, sample_rate, signal_size = _chromagram(
        np, file_path, frame_size, min_freq, max_freq
    )
    if chroma_frames.shape[0] == 0 or not np.any(chroma_frames):
        raise ValueError("audio has no tonal content for chord extraction")

    # Assign each frame to a window by the time of its centre, then average per window.
    frames_per_window = max(1, int(round(window_seconds * sample_rate / hop)))
    n_windows = int(np.ceil(chroma_frames.shape[0] / frames_per_window))
    templates = _chord_templates(np)

    window_labels: list[str] = []
    window_confidences: list[float] = []
    window_strengths = np.zeros(n_windows, dtype=np.float64)
    window_chroma = []
    for index in range(n_windows):
        block = chroma_frames[index * frames_per_window : (index + 1) * frames_per_window]
        mean = block.mean(axis=0)
        window_strengths[index] = float(mean.sum())
        window_chroma.append(mean)

    peak_strength = float(window_strengths.max())
    silence_floor = peak_strength * silence_ratio
    for index in range(n_windows):
        mean = window_chroma[index]
        if window_strengths[index] <= silence_floor or not np.any(mean):
            window_labels.append("N")
            window_confidences.append(0.0)
            continue
        unit = mean / mean.sum()
        best_label, best_corr = "N", -2.0
        for label, template in templates:
            corr = _pearson(np, unit, template)
            if corr > best_corr:
                best_label, best_corr = label, corr
        window_labels.append(best_label)
        window_confidences.append(round(max(0.0, min(1.0, best_corr)), 4))

    # Merge consecutive equal labels into timed segments.
    seconds_per_window = frames_per_window * hop / sample_rate
    segments: list[dict[str, Any]] = []
    for index, label in enumerate(window_labels):
        start = round(index * seconds_per_window, 3)
        end = round(min((index + 1) * seconds_per_window, signal_size / sample_rate), 3)
        if segments and segments[-1]["chord"] == label:
            segments[-1]["end_seconds"] = end
            segments[-1]["_confidences"].append(window_confidences[index])
        else:
            segments.append(
                {
                    "chord": label,
                    "start_seconds": start,
                    "end_seconds": end,
                    "_confidences": [window_confidences[index]],
                }
            )
    for segment in segments:
        confidences = segment.pop("_confidences")
        segment["confidence"] = round(sum(confidences) / len(confidences), 4)

    progression = [segment["chord"] for segment in segments if segment["chord"] != "N"]

    return {
        "read_only": True,
        "file": str(file_path),
        "chords": segments,
        "progression": progression,
        "window_seconds": round(seconds_per_window, 4),
        "sample_rate": sample_rate,
        "duration_seconds": round(signal_size / sample_rate, 3),
        "method": "chroma-triad-template-matching",
    }


def _note_name(midi: int) -> str:
    """MIDI number -> scientific pitch name, e.g. 60 -> ``C4`` (A4 = 69 = 440 Hz)."""
    return "%s%d" % (_NOTE_NAMES[midi % 12], midi // 12 - 1)


def _yin_pitch(np, frame, min_lag: int, max_lag: int, threshold: float):
    """One frame's fundamental via the YIN difference function.

    Returns ``(f0_lag, aperiodicity)`` where ``f0_lag`` is the (parabolically refined) lag in
    samples of the fundamental period and ``aperiodicity`` is YIN's ``d'`` at that lag (lower
    == more clearly pitched). ``f0_lag`` is ``None`` when no lag clears the threshold, which
    marks the frame as unvoiced.
    """
    integration = frame.size - max_lag
    if integration <= 0:
        return None, 1.0
    head = frame[:integration]
    difference = np.empty(max_lag + 1, dtype=np.float64)
    difference[0] = 0.0
    for lag in range(1, max_lag + 1):
        delta = head - frame[lag : lag + integration]
        difference[lag] = float(np.dot(delta, delta))

    # Cumulative mean normalised difference: this is what lets YIN reject the octave-below
    # errors a plain autocorrelation makes.
    lags = np.arange(1, max_lag + 1)
    cumulative = np.cumsum(difference[1:])
    normalised = np.ones(max_lag + 1, dtype=np.float64)
    normalised[1:] = difference[1:] * lags / np.where(cumulative > 0.0, cumulative, 1e-12)

    # Absolute threshold: the first dip below `threshold`, descended to its local minimum.
    chosen = -1
    lag = min_lag
    while lag <= max_lag:
        if normalised[lag] < threshold:
            while lag + 1 <= max_lag and normalised[lag + 1] < normalised[lag]:
                lag += 1
            chosen = lag
            break
        lag += 1
    voiced = chosen != -1
    if not voiced:
        chosen = min_lag + int(np.argmin(normalised[min_lag : max_lag + 1]))

    refined = float(chosen)
    if min_lag <= chosen < max_lag:
        a, b, c = normalised[chosen - 1], normalised[chosen], normalised[chosen + 1]
        denom = a - 2.0 * b + c
        if denom != 0.0:
            refined = chosen + max(-1.0, min(1.0, 0.5 * (a - c) / denom))

    return (refined if voiced else None), float(normalised[chosen])


def extract_melody(
    file_path: str,
    *,
    frame_size: int = 2048,
    hop: int = 512,
    min_f0: float = 65.0,
    max_f0: float = 1047.0,
    threshold: float = 0.1,
    silence_ratio: float = 0.05,
    min_note_seconds: float = 0.05,
) -> dict[str, Any]:
    """Extract a monophonic melody (note sequence) from an audio file, offline.

    Method: a self-written YIN pitch tracker estimates the fundamental of each Hann-windowed
    frame (cumulative-mean-normalised difference function + absolute threshold + parabolic
    interpolation), voiced frames are quantised to the nearest MIDI note, and consecutive
    equal notes are merged into timed segments. Assumes a single melodic line -- it does not
    resolve polyphony. Deterministic and read-only; never touches Live.
    """
    np = _require_numpy()
    if frame_size < 512 or frame_size & (frame_size - 1):
        raise ValueError("frame_size must be a power of two of at least 512")
    if hop < 64 or hop > frame_size:
        raise ValueError("hop must be between 64 and frame_size samples")
    if not 0.0 < min_f0 < max_f0:
        raise ValueError("require 0 < min_f0 < max_f0")
    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must be in (0, 1)")
    if not 0.0 <= silence_ratio < 1.0:
        raise ValueError("silence_ratio must be in [0, 1)")
    if min_note_seconds < 0.0:
        raise ValueError("min_note_seconds must not be negative")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for melody extraction (need at least ~1 second)")
    if signal.size < frame_size:
        raise ValueError("audio is shorter than one analysis frame")
    if max_f0 >= sample_rate / 2.0:
        raise ValueError("max_f0 must be below the Nyquist frequency")

    min_lag = max(1, int(sample_rate / max_f0))
    max_lag = int(sample_rate / min_f0)
    if max_lag >= frame_size:
        raise ValueError("frame_size is too small for the requested min_f0")

    window = np.hanning(frame_size)
    starts = range(0, signal.size - frame_size + 1, hop)
    frame_rms = np.array(
        [
            float(np.sqrt(np.mean((signal[start : start + frame_size]) ** 2)))
            for start in starts
        ]
    )
    peak_rms = float(frame_rms.max()) if frame_rms.size else 0.0
    silence_floor = peak_rms * silence_ratio

    # Per-frame MIDI note (or None when unvoiced), with its voicing confidence.
    frame_notes: list[int | None] = []
    frame_conf: list[float] = []
    for index, start in enumerate(starts):
        if frame_rms[index] <= silence_floor:
            frame_notes.append(None)
            frame_conf.append(0.0)
            continue
        frame = signal[start : start + frame_size] * window
        lag, aperiodicity = _yin_pitch(np, frame, min_lag, max_lag, threshold)
        if lag is None:
            frame_notes.append(None)
            frame_conf.append(0.0)
            continue
        f0 = sample_rate / lag
        midi = int(round(69.0 + 12.0 * np.log2(f0 / 440.0)))
        frame_notes.append(midi)
        frame_conf.append(round(max(0.0, min(1.0, 1.0 - aperiodicity)), 4))

    # Merge consecutive equal notes into timed segments; unvoiced frames break the line.
    hop_seconds = hop / sample_rate
    duration = signal.size / sample_rate
    raw: list[dict[str, Any]] = []
    for index, midi in enumerate(frame_notes):
        if midi is None:
            continue
        start = index * hop_seconds
        end = min(duration, start + hop_seconds)
        if raw and raw[-1]["midi"] == midi and abs(raw[-1]["end_seconds"] - start) < 1e-9:
            raw[-1]["end_seconds"] = end
            raw[-1]["_confidences"].append(frame_conf[index])
        else:
            raw.append(
                {
                    "midi": midi,
                    "start_seconds": start,
                    "end_seconds": end,
                    "_confidences": [frame_conf[index]],
                }
            )

    notes: list[dict[str, Any]] = []
    for segment in raw:
        confidences = segment.pop("_confidences")
        if segment["end_seconds"] - segment["start_seconds"] < min_note_seconds:
            continue
        midi = segment["midi"]
        notes.append(
            {
                "midi": midi,
                "note": _note_name(midi),
                "start_seconds": round(segment["start_seconds"], 3),
                "end_seconds": round(segment["end_seconds"], 3),
                "confidence": round(sum(confidences) / len(confidences), 4),
            }
        )

    return {
        "read_only": True,
        "file": str(file_path),
        "notes": notes,
        "note_names": [note["note"] for note in notes],
        "f0_range_hz": [min_f0, max_f0],
        "frame_seconds": round(hop_seconds, 4),
        "sample_rate": sample_rate,
        "duration_seconds": round(duration, 3),
        "method": "yin-monophonic-pitch",
    }


def detect_onsets(
    file_path: str,
    *,
    hop: int = 256,
    delta: float = 0.07,
    min_gap_seconds: float = 0.03,
) -> dict[str, Any]:
    """Detect note/transient onset times in an audio file, offline and deterministically.

    Method: the shared per-hop onset-strength envelope (rise in log energy) is normalised,
    then peak-picked -- a frame is an onset when it is a local maximum and rises ``delta``
    above the local moving average, with at least ``min_gap_seconds`` since the last onset.
    Returns onset times in seconds. Read-only; never touches Live.
    """
    np = _require_numpy()
    if hop < 64:
        raise ValueError("hop must be at least 64 samples")
    if not 0.0 <= delta < 1.0:
        raise ValueError("delta must be in [0, 1)")
    if min_gap_seconds < 0.0:
        raise ValueError("min_gap_seconds must not be negative")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for onset detection (need at least ~1 second)")

    onset = _onset_strength(np, signal, hop)
    peak = float(onset.max()) if onset.size else 0.0
    if peak <= 0.0:
        raise ValueError("audio has no detectable onsets")
    envelope = onset / peak  # normalise to [0, 1] so `delta` is scale-independent

    fps = sample_rate / hop
    # Local-maximum and moving-average windows, in frames.
    local = max(1, int(round(0.03 * fps)))
    average = max(1, int(round(0.10 * fps)))
    min_gap = int(round(min_gap_seconds * fps))

    n = envelope.size
    cumulative = np.concatenate(([0.0], np.cumsum(envelope)))
    onsets: list[dict[str, Any]] = []
    last = -min_gap - 1
    for index in range(n):
        lo = max(0, index - local)
        hi = min(n, index + local + 1)
        if envelope[index] < envelope[lo:hi].max():
            continue
        alo = max(0, index - average)
        ahi = min(n, index + average + 1)
        moving_average = (cumulative[ahi] - cumulative[alo]) / (ahi - alo)
        if envelope[index] < moving_average + delta:
            continue
        if index - last <= min_gap:
            # Keep the stronger of two peaks that fall within the guard window.
            if onsets and envelope[index] > onsets[-1]["strength_raw"]:
                onsets[-1] = _onset_record(index, hop, sample_rate, envelope[index])
                last = index
            continue
        onsets.append(_onset_record(index, hop, sample_rate, envelope[index]))
        last = index

    for record in onsets:
        record.pop("strength_raw", None)

    return {
        "read_only": True,
        "file": str(file_path),
        "onsets": onsets,
        "onset_times": [record["time_seconds"] for record in onsets],
        "onset_count": len(onsets),
        "frame_seconds": round(hop / sample_rate, 5),
        "sample_rate": sample_rate,
        "duration_seconds": round(signal.size / sample_rate, 3),
        "method": "log-energy-flux-peak-picking",
    }


def _onset_record(index: int, hop: int, sample_rate: int, strength: float) -> dict[str, Any]:
    # Envelope frame i is the rise between hop i and i+1, so its time is (i + 1) * hop.
    return {
        "time_seconds": round((index + 1) * hop / sample_rate, 4),
        "strength": round(float(strength), 4),
        "strength_raw": float(strength),
    }


def track_beats(
    file_path: str,
    *,
    min_bpm: float = 60.0,
    max_bpm: float = 200.0,
    hop: int = 256,
    beats_per_bar: int = 4,
) -> dict[str, Any]:
    """Track the beat grid of an audio file, offline and deterministically.

    Method: estimate the tempo from the onset envelope (shared with :func:`estimate_tempo`),
    then fit the beat phase by sliding a constant-period pulse comb over the envelope and
    keeping the offset whose beat positions collect the most onset energy. Beats are laid on
    a constant-tempo grid; ``beats_per_bar`` groups them into bar starts assuming the first
    beat is a downbeat (no true meter/downbeat detection). Read-only; never touches Live.
    """
    np = _require_numpy()
    if not 20.0 <= min_bpm < max_bpm <= 400.0:
        raise ValueError("require 20 <= min_bpm < max_bpm <= 400")
    if hop < 64:
        raise ValueError("hop must be at least 64 samples")
    if not 1 <= beats_per_bar <= 16:
        raise ValueError("beats_per_bar must be between 1 and 16")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for beat tracking (need at least ~1 second)")

    envelope = _onset_strength(np, signal, hop)
    peak = float(envelope.max()) if envelope.size else 0.0
    if peak <= 0.0:
        raise ValueError("audio has no detectable onsets for beat tracking")

    fps = sample_rate / hop
    tempo, tempo_confidence = _tempo_from_onset(np, envelope - envelope.mean(), fps, min_bpm, max_bpm)
    period = 60.0 * fps / tempo  # beat period in envelope frames

    # Fit the phase: slide the comb over one beat period and keep the offset whose beat
    # positions (linearly interpolated into the envelope) collect the most onset energy.
    n = envelope.size
    frames = np.arange(n)
    beat_count = int(np.floor((n - 1) / period)) + 1
    steps = max(8, int(round(period)))
    best_phase, best_score = 0.0, -1.0
    for step in range(steps):
        phase = step * period / steps
        positions = phase + np.arange(beat_count) * period
        positions = positions[positions <= n - 1]
        score = float(np.interp(positions, frames, envelope).sum())
        if score > best_score:
            best_score, best_phase = score, phase

    positions = best_phase + np.arange(beat_count) * period
    positions = positions[positions <= n - 1]
    strengths = np.interp(positions, frames, envelope) / peak
    beats = [
        {
            "time_seconds": round((position + 1) * hop / sample_rate, 4),
            "strength": round(float(strength), 4),
        }
        for position, strength in zip(positions, strengths)
    ]
    beat_times = [beat["time_seconds"] for beat in beats]

    return {
        "read_only": True,
        "file": str(file_path),
        "tempo_bpm": round(float(tempo), 2),
        "tempo_confidence": round(max(0.0, min(1.0, tempo_confidence)), 4),
        "beats": beats,
        "beat_times": beat_times,
        "beat_count": len(beats),
        "beat_period_seconds": round(60.0 / tempo, 4),
        "first_beat_seconds": beat_times[0] if beat_times else None,
        "beats_per_bar": beats_per_bar,
        "bar_start_times": beat_times[::beats_per_bar],
        "sample_rate": sample_rate,
        "duration_seconds": round(signal.size / sample_rate, 3),
        "method": "onset-autocorrelation-comb-phase",
    }


def _summary(np, values) -> dict[str, float]:
    """Mean/std/min/max of a 1-D array, rounded, for one feature's frame distribution."""
    return {
        "mean": round(float(np.mean(values)), 4),
        "std": round(float(np.std(values)), 4),
        "min": round(float(np.min(values)), 4),
        "max": round(float(np.max(values)), 4),
    }


def extract_spectral_features(
    file_path: str,
    *,
    frame_size: int = 2048,
    hop: int = 512,
    rolloff_percent: float = 0.85,
    silence_ratio: float = 0.05,
) -> dict[str, Any]:
    """Extract timbral spectral features from an audio file, offline and deterministically.

    Per Hann-windowed frame it computes the spectral centroid (brightness), bandwidth
    (spread), rolloff (the frequency below which ``rolloff_percent`` of the energy sits), and
    flatness (tonal vs noise-like), plus the time-domain zero-crossing rate and RMS level.
    Frames quieter than ``silence_ratio`` of the loudest frame are skipped, and each feature
    is summarised (mean/std/min/max) over the remaining frames. Read-only; never touches Live.
    """
    np = _require_numpy()
    if frame_size < 512 or frame_size & (frame_size - 1):
        raise ValueError("frame_size must be a power of two of at least 512")
    if hop < 64 or hop > frame_size:
        raise ValueError("hop must be between 64 and frame_size samples")
    if not 0.0 < rolloff_percent < 1.0:
        raise ValueError("rolloff_percent must be in (0, 1)")
    if not 0.0 <= silence_ratio < 1.0:
        raise ValueError("silence_ratio must be in [0, 1)")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for spectral analysis (need at least ~1 second)")
    if signal.size < frame_size:
        raise ValueError("audio is shorter than one analysis frame")

    freqs = np.fft.rfftfreq(frame_size, 1.0 / sample_rate)
    window = np.hanning(frame_size)
    starts = range(0, signal.size - frame_size + 1, hop)

    magnitudes = []
    raw_frames = []
    for start in starts:
        raw = signal[start : start + frame_size]
        raw_frames.append(raw)
        magnitudes.append(np.abs(np.fft.rfft(raw * window)))
    magnitude = np.asarray(magnitudes)  # (n_frames, n_bins)
    raw = np.asarray(raw_frames)  # (n_frames, frame_size)

    energy = magnitude.sum(axis=1)
    peak = float(energy.max()) if energy.size else 0.0
    if peak <= 0.0:
        raise ValueError("audio has no spectral energy for analysis")
    voiced = energy > peak * silence_ratio
    magnitude = magnitude[voiced]
    raw = raw[voiced]
    total = magnitude.sum(axis=1)

    centroid = (magnitude * freqs).sum(axis=1) / total
    bandwidth = np.sqrt((magnitude * (freqs - centroid[:, None]) ** 2).sum(axis=1) / total)

    cumulative = np.cumsum(magnitude, axis=1)
    thresholds = rolloff_percent * total
    rolloff_bins = (cumulative < thresholds[:, None]).sum(axis=1)
    rolloff = freqs[np.minimum(rolloff_bins, freqs.size - 1)]

    log_mean = np.mean(np.log(magnitude + 1e-12), axis=1)
    arithmetic_mean = np.mean(magnitude, axis=1)
    flatness = np.exp(log_mean) / (arithmetic_mean + 1e-12)

    signs = np.sign(raw)
    zero_crossings = np.abs(np.diff(signs, axis=1)) > 0
    zcr = zero_crossings.sum(axis=1) / (raw.shape[1] - 1)
    rms = np.sqrt(np.mean(raw ** 2, axis=1))

    return {
        "read_only": True,
        "file": str(file_path),
        "features": {
            "spectral_centroid_hz": _summary(np, centroid),
            "spectral_bandwidth_hz": _summary(np, bandwidth),
            "spectral_rolloff_hz": _summary(np, rolloff),
            "spectral_flatness": _summary(np, flatness),
            "zero_crossing_rate": _summary(np, zcr),
            "rms": _summary(np, rms),
        },
        "rolloff_percent": rolloff_percent,
        "frames_analyzed": int(magnitude.shape[0]),
        "frame_size": frame_size,
        "hop": hop,
        "sample_rate": sample_rate,
        "duration_seconds": round(signal.size / sample_rate, 3),
        "method": "stft-spectral-features",
    }


def _checkerboard_kernel(np, half: int):
    """A Gaussian-tapered checkerboard kernel for Foote structural-novelty detection.

    Positive on the top-left/bottom-right quadrants (self-similar past and future) and
    negative on the cross quadrants, so correlating it along an SSM diagonal peaks where the
    audio before a point is unlike the audio after it -- a section boundary.
    """
    coords = np.arange(-half, half) + 0.5
    a = coords[:, None]
    b = coords[None, :]
    sign = np.sign(a) * np.sign(b)
    sigma = max(1.0, half / 2.0)
    gaussian = np.exp(-(a ** 2 + b ** 2) / (2.0 * sigma ** 2))
    return sign * gaussian


_SECTION_LABELS = tuple(chr(ord("A") + i) for i in range(26))


def _label_segments(np, segments, window_vectors, label_threshold: float):
    """Assign A/B/C labels: a segment reuses the label of an earlier section it resembles."""
    label_centroids: list[tuple[str, Any]] = []
    labels: list[str] = []
    for start, end in segments:
        centroid = window_vectors[start:end].mean(axis=0)
        norm = float(np.linalg.norm(centroid))
        if norm:
            centroid = centroid / norm
        best_label, best_similarity = None, label_threshold
        for label, existing in label_centroids:
            similarity = float(centroid @ existing)
            if similarity >= best_similarity:
                best_label, best_similarity = label, similarity
        if best_label is None:
            best_label = (
                _SECTION_LABELS[len(label_centroids)]
                if len(label_centroids) < len(_SECTION_LABELS)
                else "?"
            )
            label_centroids.append((best_label, centroid))
        labels.append(best_label)
    return labels


def segment_structure(
    file_path: str,
    *,
    frame_size: int = 4096,
    window_seconds: float = 1.0,
    kernel_seconds: float = 8.0,
    min_segment_seconds: float = 4.0,
    threshold: float = 0.3,
    label_threshold: float = 0.8,
    min_freq: float = 55.0,
    max_freq: float = 5000.0,
) -> dict[str, Any]:
    """Segment an audio file into sections (intro/verse/chorus-like), offline.

    Method: the shared DFT chromagram is averaged into ``window_seconds`` windows; a cosine
    self-similarity matrix of those windows is correlated with a Gaussian checkerboard kernel
    (Foote novelty) to score each window as a possible boundary; novelty peaks become section
    boundaries, and each section is given an A/B/C label by matching its mean chroma to
    earlier sections. Harmonic structure only -- not a trained segmenter. Read-only.
    """
    np = _require_numpy()
    if not 0.1 <= window_seconds <= 10.0:
        raise ValueError("window_seconds must be between 0.1 and 10")
    if kernel_seconds < 2 * window_seconds:
        raise ValueError("kernel_seconds must be at least two windows")
    if min_segment_seconds < window_seconds:
        raise ValueError("min_segment_seconds must be at least one window")
    if not 0.0 <= threshold < 1.0:
        raise ValueError("threshold must be in [0, 1)")
    if not 0.0 < label_threshold <= 1.0:
        raise ValueError("label_threshold must be in (0, 1]")

    chroma_frames, hop, sample_rate, signal_size = _chromagram(
        np, file_path, frame_size, min_freq, max_freq
    )
    duration = signal_size / sample_rate

    fps = sample_rate / hop
    frames_per_window = max(1, int(round(window_seconds * fps)))
    n_frames = chroma_frames.shape[0]
    n_windows = int(np.ceil(n_frames / frames_per_window)) if n_frames else 0
    if n_windows < 4:
        raise ValueError("audio is too short for structural segmentation (need several windows)")

    # One L2-normalised chroma vector per window, then a cosine self-similarity matrix.
    windows = np.zeros((n_windows, 12), dtype=np.float64)
    for index in range(n_windows):
        block = chroma_frames[index * frames_per_window : (index + 1) * frames_per_window]
        vector = block.mean(axis=0)
        norm = float(np.linalg.norm(vector))
        windows[index] = vector / norm if norm else vector
    ssm = windows @ windows.T

    half = min(n_windows // 2, max(1, int(round(kernel_seconds / window_seconds / 2.0))))
    kernel = _checkerboard_kernel(np, half)
    offsets = np.arange(-half, half)
    denom = float(np.abs(kernel).sum())
    novelty = np.zeros(n_windows, dtype=np.float64)
    # Only score windows where the full kernel fits; partial kernels at the very start/end
    # produce spurious novelty spikes that would swamp the real interior boundaries.
    for i in range(half, n_windows - half):
        picked = i + offsets
        novelty[i] = float((kernel * ssm[np.ix_(picked, picked)]).sum()) / denom

    span = float(novelty.max() - novelty.min())
    normalised = (novelty - novelty.min()) / span if span else np.zeros_like(novelty)

    # Peak-pick the novelty curve into boundary windows.
    min_gap = max(1, int(round(min_segment_seconds / window_seconds)))
    peaks: list[int] = []
    for i in range(n_windows):
        lo = max(0, i - 1)
        hi = min(n_windows, i + 2)
        if normalised[i] < normalised[lo:hi].max() or normalised[i] < threshold:
            continue
        if peaks and i - peaks[-1] < min_gap:
            if normalised[i] > normalised[peaks[-1]]:
                peaks[-1] = i
            continue
        peaks.append(i)

    boundaries = [0.0]
    for peak in peaks:
        time = round(peak * window_seconds, 3)
        if time - boundaries[-1] >= min_segment_seconds and duration - time >= min_segment_seconds:
            boundaries.append(time)
    boundaries.append(round(duration, 3))

    window_segments = [
        (int(round(boundaries[i] / window_seconds)), int(round(boundaries[i + 1] / window_seconds)))
        for i in range(len(boundaries) - 1)
    ]
    labels = _label_segments(np, window_segments, windows, label_threshold)
    segments = [
        {
            "start_seconds": boundaries[i],
            "end_seconds": boundaries[i + 1],
            "label": labels[i],
        }
        for i in range(len(boundaries) - 1)
    ]

    return {
        "read_only": True,
        "file": str(file_path),
        "segments": segments,
        "boundaries_seconds": boundaries,
        "segment_count": len(segments),
        "labels": labels,
        "window_seconds": window_seconds,
        "sample_rate": sample_rate,
        "duration_seconds": round(duration, 3),
        "method": "chroma-ssm-foote-novelty",
    }


# Default tonal-balance bands (name, low Hz, high Hz), spanning the audible range.
_DEFAULT_BANDS = (
    ("low", 20.0, 120.0),
    ("low_mid", 120.0, 500.0),
    ("mid", 500.0, 2000.0),
    ("high_mid", 2000.0, 6000.0),
    ("high", 6000.0, 20000.0),
)


def extract_spectral_bands(
    file_path: str,
    *,
    frame_size: int = 2048,
    hop: int = 512,
    bands: tuple[tuple[str, float, float], ...] = _DEFAULT_BANDS,
) -> dict[str, Any]:
    """Extract a level-independent tonal balance: the fraction of energy in each band.

    Sums the STFT power spectrum over the whole file, then reports each band's share of the
    in-band total, so the result describes *tone* independent of overall loudness -- ideal
    for comparing a mix against a reference. Read-only; never touches Live.
    """
    np = _require_numpy()
    if frame_size < 512 or frame_size & (frame_size - 1):
        raise ValueError("frame_size must be a power of two of at least 512")
    if hop < 64 or hop > frame_size:
        raise ValueError("hop must be between 64 and frame_size samples")
    if not bands:
        raise ValueError("at least one band is required")

    signal, sample_rate = _read_mono(Path(file_path))
    if signal.size < sample_rate:
        raise ValueError("audio is too short for band analysis (need at least ~1 second)")
    if signal.size < frame_size:
        raise ValueError("audio is shorter than one analysis frame")

    freqs = np.fft.rfftfreq(frame_size, 1.0 / sample_rate)
    window = np.hanning(frame_size)
    power = np.zeros(freqs.size, dtype=np.float64)
    for start in range(0, signal.size - frame_size + 1, hop):
        magnitude = np.abs(np.fft.rfft(signal[start : start + frame_size] * window))
        power += magnitude ** 2

    band_power = []
    for name, low_hz, high_hz in bands:
        mask = (freqs >= low_hz) & (freqs < high_hz)
        band_power.append((name, low_hz, high_hz, float(power[mask].sum())))
    total = sum(entry[3] for entry in band_power)
    if total <= 0.0:
        raise ValueError("audio has no spectral energy in the requested bands")

    band_list = [
        {
            "name": name,
            "low_hz": low_hz,
            "high_hz": high_hz,
            "fraction": round(value / total, 6),
        }
        for name, low_hz, high_hz, value in band_power
    ]
    return {
        "read_only": True,
        "file": str(file_path),
        "bands": band_list,
        "band_fractions": {entry["name"]: entry["fraction"] for entry in band_list},
        "sample_rate": sample_rate,
        "duration_seconds": round(signal.size / sample_rate, 3),
        "method": "stft-power-band-balance",
    }


def analyze_stereo_field(file_path: str) -> dict[str, Any]:
    """Measure an audio file's stereo image: width, L/R phase correlation, and balance.

    Uses a mid/side decomposition. ``width_side_ratio`` is the side channel's share of the
    energy (0 = mono, ~0.5 = fully decorrelated, 1 = anti-phase). ``correlation`` is the L/R
    phase-meter value (+1 in phase/mono-safe, 0 decorrelated, -1 anti-phase). ``balance_db``
    is positive when the left channel is louder. Mono files report width 0 / correlation 1.
    Read-only; never touches Live.
    """
    np = _require_numpy()
    samples, sample_rate, channels = _read_channels(Path(file_path))
    if samples.shape[0] < sample_rate:
        raise ValueError("audio is too short for stereo analysis (need at least ~1 second)")

    duration = round(samples.shape[0] / sample_rate, 3)
    if channels < 2:
        return {
            "read_only": True,
            "file": str(file_path),
            "channels": channels,
            "is_stereo": False,
            "width_side_ratio": 0.0,
            "correlation": 1.0,
            "balance_db": 0.0,
            "sample_rate": sample_rate,
            "duration_seconds": duration,
            "method": "mid-side-correlation",
            "note": "audio is mono; reported as fully centred",
        }

    left = samples[:, 0]
    right = samples[:, 1]
    left_energy = float(np.sum(left ** 2))
    right_energy = float(np.sum(right ** 2))
    mid = 0.5 * (left + right)
    side = 0.5 * (left - right)
    mid_energy = float(np.sum(mid ** 2))
    side_energy = float(np.sum(side ** 2))
    total = mid_energy + side_energy
    if total <= 0.0:
        raise ValueError("audio has no energy for stereo analysis")

    denominator = math.sqrt(left_energy * right_energy)
    correlation = float(np.sum(left * right) / denominator) if denominator > 0.0 else 1.0
    if left_energy > 0.0 and right_energy > 0.0:
        balance_db = 10.0 * math.log10(left_energy / right_energy)
    else:
        balance_db = 0.0

    return {
        "read_only": True,
        "file": str(file_path),
        "channels": channels,
        "is_stereo": True,
        "width_side_ratio": round(side_energy / total, 4),
        "correlation": round(max(-1.0, min(1.0, correlation)), 4),
        "balance_db": round(balance_db, 2),
        "mid_energy_fraction": round(mid_energy / total, 4),
        "side_energy_fraction": round(side_energy / total, 4),
        "sample_rate": sample_rate,
        "duration_seconds": duration,
        "method": "mid-side-correlation",
    }
