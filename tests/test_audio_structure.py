"""Tests for offline structural segmentation.

Deterministic and self-contained: each test synthesizes a signal with a known section
layout (harmonically distinct blocks), writes it to a temp WAV with the stdlib ``wave``
module, and checks the detected boundaries and labels. Needs the optional ``audio`` extra
(NumPy); skipped cleanly when it is absent.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from abletongpt.audio import segment_structure


_SR = 22050
_NOTE_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _midi_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _triad(root: str, seconds: float):
    root_midi = 48 + _NOTE_INDEX[root]
    t = np.arange(int(_SR * seconds))
    tone = sum(np.sin(2 * np.pi * _midi_hz(root_midi + i) * t / _SR) for i in (0, 4, 7)) / 3
    return tone


def _sections(layout, seconds_each: float):
    return np.concatenate([_triad(root, seconds_each) for root in layout])


def _write_wav(path: Path, signal) -> Path:
    data = (np.clip(signal * 0.5, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SR)
        handle.writeframes(data.tobytes())
    return path


def _closest(values, target):
    return min(values, key=lambda value: abs(value - target))


def test_detects_section_boundaries(tmp_path: Path):
    # C for 5 s, F for 5 s, C for 5 s -> boundaries near 5 and 10 s.
    wav = _write_wav(tmp_path / "aba.wav", _sections(["C", "F", "C"], 5.0))

    result = segment_structure(str(wav))

    assert result["read_only"] is True
    assert result["segment_count"] == 3
    boundaries = result["boundaries_seconds"]
    assert boundaries[0] == 0.0
    assert abs(_closest(boundaries, 5.0) - 5.0) <= 1.0
    assert abs(_closest(boundaries, 10.0) - 10.0) <= 1.0


def test_labels_repeat_for_similar_sections(tmp_path: Path):
    # A B A: the two C-major sections should share a label distinct from the F section.
    wav = _write_wav(tmp_path / "aba.wav", _sections(["C", "F", "C"], 5.0))

    labels = segment_structure(str(wav))["labels"]

    assert labels[0] == labels[2]
    assert labels[1] != labels[0]


def test_segments_are_contiguous_and_cover_duration(tmp_path: Path):
    wav = _write_wav(tmp_path / "aba.wav", _sections(["C", "G", "C"], 5.0))

    result = segment_structure(str(wav))
    segments = result["segments"]

    assert segments[0]["start_seconds"] == 0.0
    for earlier, later in zip(segments, segments[1:]):
        assert earlier["end_seconds"] == later["start_seconds"]
    assert segments[-1]["end_seconds"] == pytest.approx(result["duration_seconds"], abs=1.0)


def test_is_deterministic(tmp_path: Path):
    wav = _write_wav(tmp_path / "aba.wav", _sections(["C", "F", "C"], 4.0))

    assert segment_structure(str(wav)) == segment_structure(str(wav))


def test_rejects_too_short_audio(tmp_path: Path):
    wav = _write_wav(tmp_path / "short.wav", _triad("C", 2.0))

    with pytest.raises(ValueError):
        segment_structure(str(wav))


def test_rejects_bad_threshold(tmp_path: Path):
    wav = _write_wav(tmp_path / "aba.wav", _sections(["C", "F", "C"], 4.0))

    with pytest.raises(ValueError):
        segment_structure(str(wav), threshold=1.5)
