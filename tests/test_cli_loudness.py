"""Tests for the ``loudness`` analysis CLI.

The CLI wraps the pure ``analyze_loudness_file`` engine. Each test writes a small WAV
with the stdlib ``wave`` module -- no external fixtures, no Ableton.
"""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

from abletongpt.cli.loudness import main


def _write_tone_wav(path: Path, *, seconds: float = 1.0, sample_rate: int = 48000) -> Path:
    frames = bytearray()
    for i in range(int(sample_rate * seconds)):
        value = int(0.1 * 32767 * math.sin(2 * math.pi * 1000 * i / sample_rate))
        frames.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
    return path


def test_analyze_human_output_reports_measurements(tmp_path: Path, capsys):
    wav = _write_tone_wav(tmp_path / "tone.wav")

    rc = main(["--file", str(wav)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "tone.wav" in out
    assert "integrated:" in out
    assert "LUFS" in out
    # Without --target-lufs there is no target guidance line.
    assert "target:" not in out


def test_analyze_json_is_machine_readable(tmp_path: Path, capsys):
    wav = _write_tone_wav(tmp_path / "tone.wav", seconds=2.0)

    rc = main(["--file", str(wav), "--target-lufs", "-14", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True
    assert payload["file"]["container"] == "WAV"
    # A steady -20 dBFS tone integrates to roughly -20 LUFS.
    assert -21.5 < payload["measurements"]["integrated_lufs"] < -19.5
    # The target produces gain guidance.
    assert payload["analysis"]["target_lufs"] == -14.0
    assert payload["analysis"]["gain_to_target_db"] > 5.0


def test_analyze_missing_file_exits_2(tmp_path: Path, capsys):
    rc = main(["--file", str(tmp_path / "nope.wav")])

    assert rc == 2
    assert "does not exist" in capsys.readouterr().err


def test_analyze_unsupported_format_exits_2(tmp_path: Path, capsys):
    bogus = tmp_path / "note.txt"
    bogus.write_text("not audio", encoding="utf-8")

    rc = main(["--file", str(bogus)])

    assert rc == 2
    assert "WAV and AIFF" in capsys.readouterr().err


def test_analyze_out_of_range_target_exits_2(tmp_path: Path, capsys):
    wav = _write_tone_wav(tmp_path / "tone.wav")

    rc = main(["--file", str(wav), "--target-lufs", "-100"])

    assert rc == 2
    assert "target_lufs" in capsys.readouterr().err
