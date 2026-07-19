#!/usr/bin/env python3
"""Render a non-overwriting PCM WAV gain master while preserving its format."""

from __future__ import annotations

import argparse
import math
import wave
from pathlib import Path

import numpy as np


def _scale_pcm(block: bytes, sample_width: int, gain: float) -> bytes:
    if sample_width == 1:
        samples = np.frombuffer(block, dtype=np.uint8).astype(np.float64) - 128.0
        scaled = np.clip(np.rint(samples * gain), -128, 127).astype(np.int16) + 128
        return scaled.astype(np.uint8).tobytes()

    if sample_width == 2:
        samples = np.frombuffer(block, dtype="<i2").astype(np.float64)
        return np.clip(np.rint(samples * gain), -32768, 32767).astype("<i2").tobytes()

    if sample_width == 3:
        packed = np.frombuffer(block, dtype=np.uint8).reshape(-1, 3)
        samples = (
            packed[:, 0].astype(np.int32)
            | (packed[:, 1].astype(np.int32) << 8)
            | (packed[:, 2].astype(np.int32) << 16)
        )
        samples = np.where(samples & 0x800000, samples - 0x1000000, samples)
        scaled = np.clip(np.rint(samples * gain), -8388608, 8388607).astype(np.int32)
        unsigned = scaled & 0xFFFFFF
        output = np.empty((unsigned.size, 3), dtype=np.uint8)
        output[:, 0] = unsigned & 0xFF
        output[:, 1] = (unsigned >> 8) & 0xFF
        output[:, 2] = (unsigned >> 16) & 0xFF
        return output.tobytes()

    if sample_width == 4:
        samples = np.frombuffer(block, dtype="<i4").astype(np.float64)
        return np.clip(
            np.rint(samples * gain), -2147483648, 2147483647
        ).astype("<i4").tobytes()

    raise ValueError(f"unsupported PCM sample width: {sample_width * 8} bit")


def render_gain_master(source_path: Path, output_path: Path, gain_db: float) -> None:
    source_path = source_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if source_path.suffix.lower() != ".wav" or output_path.suffix.lower() != ".wav":
        raise ValueError("input and output must be WAV files")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    gain = math.pow(10.0, gain_db / 20.0)
    with wave.open(str(source_path), "rb") as source:
        if source.getcomptype() != "NONE":
            raise ValueError("only uncompressed PCM WAV files are supported")
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()

        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(sample_width)
            output.setframerate(sample_rate)
            while True:
                block = source.readframes(65536)
                if not block:
                    break
                output.writeframesraw(_scale_pcm(block, sample_width, gain))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--gain-db", type=float, required=True)
    args = parser.parse_args()
    render_gain_master(args.source, args.output, args.gain_db)


if __name__ == "__main__":
    main()
