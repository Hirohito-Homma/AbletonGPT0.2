from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

from abletongpt import loudness


def _write_tone(path: Path, *, seconds: float = 0.5) -> Path:
    sample_rate = 48000
    frames = bytearray()
    for index in range(int(sample_rate * seconds)):
        value = int(
            0.1 * 32767 * math.sin(2.0 * math.pi * 1000.0 * index / sample_rate)
        )
        frames.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
    return path


def test_ffmpeg_fast_path_parses_precise_delivery_measurements(
    tmp_path: Path, monkeypatch
):
    path = _write_tone(tmp_path / "mix.wav")
    stderr = """
[Parsed_ametadata_2] lavfi.r128.M=-14.500
[Parsed_ametadata_2] lavfi.r128.S=-15.250
[Parsed_ametadata_2] lavfi.r128.I=-14.125
[Parsed_ametadata_2] lavfi.r128.LRA=4.500
[Parsed_ametadata_2] lavfi.r128.true_peak=0.891251
[Parsed_astats_3] Overall
[Parsed_astats_3] Peak level dB: -1.000000
[Parsed_astats_3] RMS level dB: -12.500000
"""
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr=stderr)

    monkeypatch.setattr(loudness.shutil, "which", lambda _name: "/mock/ffmpeg")
    monkeypatch.setattr(loudness.subprocess, "run", fake_run)

    result = loudness.analyze_loudness_file(
        path,
        target_lufs=-14.0,
        target_true_peak_dbtp=-1.0,
    )

    assert result["analysis_engine"] == {
        "name": "ffmpeg-ebur128",
        "accelerated": True,
        "fallback": False,
    }
    assert result["measurements"] == {
        "integrated_lufs": -14.12,
        "loudness_range_lu": 4.5,
        "max_momentary_lufs": -14.5,
        "max_short_term_lufs": -15.25,
        "sample_peak_dbfs": -1.0,
        "true_peak_dbtp": -1.0,
        "rms_dbfs": -12.5,
        "crest_factor_db": 11.5,
    }
    assert result["file"]["duration_seconds"] == 0.5
    assert calls[0][0][0] == "/mock/ffmpeg"
    assert str(path) in calls[0][0]
    assert calls[0][1]["check"] is False


def test_ffmpeg_failure_falls_back_to_portable_python(
    tmp_path: Path, monkeypatch
):
    path = _write_tone(tmp_path / "mix.wav")

    monkeypatch.setattr(loudness.shutil, "which", lambda _name: "/mock/ffmpeg")
    monkeypatch.setattr(
        loudness.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="failed"
        ),
    )

    result = loudness.analyze_loudness_file(path)

    assert result["analysis_engine"] == {
        "name": "python",
        "accelerated": False,
        "fallback": True,
    }
    assert result["measurements"]["integrated_lufs"] is not None
