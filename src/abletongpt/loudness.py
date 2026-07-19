from __future__ import annotations

import math
import struct
from collections import deque
from pathlib import Path
from typing import Any, BinaryIO, Iterator


_ABSOLUTE_GATE_LUFS = -70.0
_LOUDNESS_OFFSET = -0.691
_SUPPORTED_SUFFIXES = {".wav", ".wave", ".aif", ".aiff", ".aifc"}


class _Biquad:
    __slots__ = ("b0", "b1", "b2", "a1", "a2", "x1", "x2", "y1", "y2")

    def __init__(
        self, b0: float, b1: float, b2: float, a1: float, a2: float
    ) -> None:
        self.b0 = b0
        self.b1 = b1
        self.b2 = b2
        self.a1 = a1
        self.a2 = a2
        self.x1 = 0.0
        self.x2 = 0.0
        self.y1 = 0.0
        self.y2 = 0.0

    def process(self, value: float) -> float:
        result = (
            self.b0 * value
            + self.b1 * self.x1
            + self.b2 * self.x2
            - self.a1 * self.y1
            - self.a2 * self.y2
        )
        self.x2 = self.x1
        self.x1 = value
        self.y2 = self.y1
        self.y1 = result
        return result


class _KWeighting:
    __slots__ = ("shelf", "high_pass")

    def __init__(self, sample_rate: int) -> None:
        # Coefficients follow the BS.1770 K-weighting stages using the
        # De Man parameterisation, recalculated for the source sample rate.
        shelf_frequency = 1681.974450955533
        shelf_gain = 3.999843853973347
        shelf_q = 0.7071752369554196
        k = math.tan(math.pi * shelf_frequency / sample_rate)
        vh = 10.0 ** (shelf_gain / 20.0)
        vb = vh ** 0.4996667741545416
        denominator = 1.0 + k / shelf_q + k * k
        self.shelf = _Biquad(
            (vh + vb * k / shelf_q + k * k) / denominator,
            2.0 * (k * k - vh) / denominator,
            (vh - vb * k / shelf_q + k * k) / denominator,
            2.0 * (k * k - 1.0) / denominator,
            (1.0 - k / shelf_q + k * k) / denominator,
        )

        high_pass_frequency = 38.13547087602444
        high_pass_q = 0.5003270373238773
        k = math.tan(math.pi * high_pass_frequency / sample_rate)
        denominator = 1.0 + k / high_pass_q + k * k
        self.high_pass = _Biquad(
            1.0 / denominator,
            -2.0 / denominator,
            1.0 / denominator,
            2.0 * (k * k - 1.0) / denominator,
            (1.0 - k / high_pass_q + k * k) / denominator,
        )

    def process(self, value: float) -> float:
        return self.high_pass.process(self.shelf.process(value))


class _TruePeakEstimator:
    """Four-times cubic inter-sample peak estimator.

    This is useful for production guidance, but it is deliberately reported as
    an estimate rather than as a certified IEC true-peak meter.
    """

    __slots__ = ("history", "sample_maximum", "true_maximum")

    def __init__(self) -> None:
        self.history: deque[float] = deque(maxlen=4)
        self.sample_maximum = 0.0
        self.true_maximum = 0.0

    def process(self, value: float) -> None:
        self.sample_maximum = max(self.sample_maximum, abs(value))
        self.true_maximum = max(self.true_maximum, abs(value))
        self.history.append(value)
        if len(self.history) < 4:
            return
        previous, start, end, following = self.history
        for position in (0.25, 0.5, 0.75):
            position2 = position * position
            position3 = position2 * position
            interpolated = 0.5 * (
                2.0 * start
                + (-previous + end) * position
                + (2.0 * previous - 5.0 * start + 4.0 * end - following)
                * position2
                + (-previous + 3.0 * start - 3.0 * end + following) * position3
            )
            self.true_maximum = max(self.true_maximum, abs(interpolated))


class _AudioStream:
    def __init__(
        self,
        file: BinaryIO,
        *,
        path: Path,
        container: str,
        sample_rate: int,
        channels: int,
        bits_per_sample: int,
        frame_count: int,
        data_offset: int,
        data_size: int,
        byte_order: str,
        encoding: str,
        unsigned_8_bit: bool,
        channel_mask: int | None = None,
    ) -> None:
        self.file = file
        self.path = path
        self.container = container
        self.sample_rate = sample_rate
        self.channels = channels
        self.bits_per_sample = bits_per_sample
        self.sample_width = bits_per_sample // 8
        self.frame_count = frame_count
        self.data_offset = data_offset
        self.data_size = data_size
        self.byte_order = byte_order
        self.encoding = encoding
        self.unsigned_8_bit = unsigned_8_bit
        self.channel_mask = channel_mask

    def __enter__(self) -> _AudioStream:
        self.file.seek(self.data_offset)
        return self

    def __exit__(self, *_args: object) -> None:
        self.file.close()

    def frames(self, chunk_frames: int = 4096) -> Iterator[list[float]]:
        frame_size = self.channels * self.sample_width
        remaining = self.frame_count
        while remaining:
            requested = min(chunk_frames, remaining)
            raw = self.file.read(requested * frame_size)
            complete_frames = len(raw) // frame_size
            if not complete_frames:
                break
            usable = raw[: complete_frames * frame_size]
            yield _decode_samples(
                usable,
                bits_per_sample=self.bits_per_sample,
                byte_order=self.byte_order,
                encoding=self.encoding,
                unsigned_8_bit=self.unsigned_8_bit,
            )
            remaining -= complete_frames


def analyze_loudness_file(
    file_path: str | Path,
    target_lufs: float | None = None,
    target_true_peak_dbtp: float = -1.0,
) -> dict[str, Any]:
    """Analyze an uncompressed WAV/AIFF file without modifying it."""
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("audio file does not exist")
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError("loudness analysis supports WAV and AIFF files")
    if target_lufs is not None and not -36.0 <= target_lufs <= -5.0:
        raise ValueError("target_lufs must be between -36 and -5")
    if not -9.0 <= target_true_peak_dbtp <= 0.0:
        raise ValueError("target_true_peak_dbtp must be between -9 and 0")

    with _open_audio(path) as audio:
        if not 8000 <= audio.sample_rate <= 384000:
            raise ValueError("sample rate must be between 8000 and 384000 Hz")
        if not 1 <= audio.channels <= 32:
            raise ValueError("audio must contain between 1 and 32 channels")
        weights, layout_note = _channel_weights(audio.channels, audio.channel_mask)
        filters = [_KWeighting(audio.sample_rate) for _ in range(audio.channels)]
        peak_estimators = [_TruePeakEstimator() for _ in range(audio.channels)]
        hop_samples = max(1, round(audio.sample_rate * 0.1))
        current_hop_energy = 0.0
        current_hop_count = 0
        hop_energies: list[float] = []
        momentary_energies: list[float] = []
        short_term_energies: list[float] = []
        unweighted_square_sum = 0.0
        decoded_samples = 0

        for samples in audio.frames():
            for offset in range(0, len(samples), audio.channels):
                frame = samples[offset : offset + audio.channels]
                if len(frame) < audio.channels:
                    break
                weighted_square = 0.0
                for channel, value in enumerate(frame):
                    if not math.isfinite(value):
                        raise ValueError("audio contains a non-finite sample")
                    unweighted_square_sum += value * value
                    peak_estimators[channel].process(value)
                    filtered = filters[channel].process(value)
                    weighted_square += weights[channel] * filtered * filtered
                decoded_samples += audio.channels
                current_hop_energy += weighted_square
                current_hop_count += 1
                if current_hop_count == hop_samples:
                    hop_energies.append(current_hop_energy / hop_samples)
                    current_hop_energy = 0.0
                    current_hop_count = 0
                    if len(hop_energies) >= 4:
                        momentary_energies.append(sum(hop_energies[-4:]) / 4.0)
                    if len(hop_energies) >= 30:
                        short_term_energies.append(sum(hop_energies[-30:]) / 30.0)

        if decoded_samples == 0:
            raise ValueError("audio file contains no decodable frames")

        integrated = _integrated_loudness(momentary_energies)
        momentary_values = [_energy_to_lufs(value) for value in momentary_energies]
        short_term_values = [_energy_to_lufs(value) for value in short_term_energies]
        sample_peak = max(estimator.sample_maximum for estimator in peak_estimators)
        # Every true maximum includes sample peaks; cubic values add an inter-sample estimate.
        true_peak = max(estimator.true_maximum for estimator in peak_estimators)
        rms = math.sqrt(unweighted_square_sum / decoded_samples)
        sample_peak_dbfs = _amplitude_to_dbfs(sample_peak)
        true_peak_dbtp = _amplitude_to_dbfs(true_peak)
        rms_dbfs = _amplitude_to_dbfs(rms)
        crest_factor = (
            sample_peak_dbfs - rms_dbfs
            if sample_peak_dbfs is not None and rms_dbfs is not None
            else None
        )
        lra = _loudness_range(short_term_values[::10])

        measurements = {
            "integrated_lufs": _rounded(integrated),
            "loudness_range_lu": _rounded(lra),
            "max_momentary_lufs": _rounded(_finite_max(momentary_values)),
            "max_short_term_lufs": _rounded(_finite_max(short_term_values)),
            "sample_peak_dbfs": _rounded(sample_peak_dbfs),
            "true_peak_dbtp": _rounded(true_peak_dbtp),
            "rms_dbfs": _rounded(rms_dbfs),
            "crest_factor_db": _rounded(crest_factor),
        }
        duration_seconds = (decoded_samples / audio.channels) / audio.sample_rate
        result: dict[str, Any] = {
            "file": {
                "path": str(path),
                "name": path.name,
                "container": audio.container,
                "sample_rate_hz": audio.sample_rate,
                "channels": audio.channels,
                "bit_depth": audio.bits_per_sample,
                "duration_seconds": round(duration_seconds, 3),
            },
            "standard": {
                "loudness": "ITU-R BS.1770 K-weighting with EBU R128 gating",
                "momentary_window_seconds": 0.4,
                "short_term_window_seconds": 3.0,
                "true_peak": "4x cubic inter-sample estimate; not a certified delivery meter",
            },
            "measurements": measurements,
            "analysis": _build_analysis(
                measurements, target_lufs, target_true_peak_dbtp
            ),
            "quality_notes": [
                layout_note,
                "最終納品では認証済みTrue Peakメーターとの照合を推奨します。",
                "LUFS目標はジャンル、マスターの意図、配信仕様と聴感を合わせて決めてください。",
            ],
            "read_only": True,
        }
        return result


def _open_audio(path: Path) -> _AudioStream:
    suffix = path.suffix.lower()
    if suffix in {".wav", ".wave"}:
        return _open_wave(path)
    return _open_aiff(path)


def _open_wave(path: Path) -> _AudioStream:
    file = path.open("rb")
    try:
        header = file.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise ValueError("invalid or unsupported WAV container")
        fmt: bytes | None = None
        data_offset: int | None = None
        data_size: int | None = None
        while True:
            chunk_header = file.read(8)
            if len(chunk_header) < 8:
                break
            chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)
            chunk_start = file.tell()
            if chunk_id == b"fmt ":
                fmt = file.read(chunk_size)
            elif chunk_id == b"data":
                data_offset = chunk_start
                data_size = chunk_size
            file.seek(chunk_start + chunk_size + (chunk_size & 1))
        if fmt is None or data_offset is None or data_size is None or len(fmt) < 16:
            raise ValueError("WAV file is missing fmt or data chunks")
        audio_format, channels, sample_rate, _byte_rate, block_align, bits = struct.unpack(
            "<HHIIHH", fmt[:16]
        )
        channel_mask: int | None = None
        if audio_format == 0xFFFE and len(fmt) >= 40:
            channel_mask = struct.unpack("<I", fmt[20:24])[0]
            audio_format = struct.unpack("<H", fmt[24:26])[0]
        if audio_format not in {1, 3}:
            raise ValueError("WAV encoding must be PCM integer or IEEE float")
        encoding = "float" if audio_format == 3 else "pcm"
        _validate_audio_format(channels, sample_rate, bits, block_align, encoding)
        frame_count = data_size // block_align
        return _AudioStream(
            file,
            path=path,
            container="WAV",
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=bits,
            frame_count=frame_count,
            data_offset=data_offset,
            data_size=data_size,
            byte_order="little",
            encoding=encoding,
            unsigned_8_bit=encoding == "pcm" and bits == 8,
            channel_mask=channel_mask,
        )
    except Exception:
        file.close()
        raise


def _open_aiff(path: Path) -> _AudioStream:
    file = path.open("rb")
    try:
        header = file.read(12)
        if len(header) != 12 or header[:4] != b"FORM" or header[8:] not in {b"AIFF", b"AIFC"}:
            raise ValueError("invalid or unsupported AIFF container")
        form_type = header[8:]
        comm: bytes | None = None
        sound_offset: int | None = None
        sound_size: int | None = None
        while True:
            chunk_header = file.read(8)
            if len(chunk_header) < 8:
                break
            chunk_id, chunk_size = struct.unpack(">4sI", chunk_header)
            chunk_start = file.tell()
            if chunk_id == b"COMM":
                comm = file.read(chunk_size)
            elif chunk_id == b"SSND" and chunk_size >= 8:
                offset, _block_size = struct.unpack(">II", file.read(8))
                sound_offset = chunk_start + 8 + offset
                sound_size = max(0, chunk_size - 8 - offset)
            file.seek(chunk_start + chunk_size + (chunk_size & 1))
        if comm is None or sound_offset is None or sound_size is None or len(comm) < 18:
            raise ValueError("AIFF file is missing COMM or SSND chunks")
        channels, declared_frames, bits = struct.unpack(">hIh", comm[:8])
        sample_rate = round(_decode_extended_80(comm[8:18]))
        compression = comm[18:22] if form_type == b"AIFC" and len(comm) >= 22 else b"NONE"
        if compression in {b"NONE", b"twos"}:
            byte_order = "big"
            encoding = "pcm"
        elif compression == b"sowt":
            byte_order = "little"
            encoding = "pcm"
        elif compression in {b"fl32", b"FL32", b"fl64", b"FL64"}:
            byte_order = "big"
            encoding = "float"
        else:
            raise ValueError("AIFF compression must be uncompressed PCM or IEEE float")
        sample_width = bits // 8
        block_align = channels * sample_width
        _validate_audio_format(channels, sample_rate, bits, block_align, encoding)
        available_frames = sound_size // block_align
        frame_count = min(declared_frames, available_frames)
        return _AudioStream(
            file,
            path=path,
            container="AIFF-C" if form_type == b"AIFC" else "AIFF",
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=bits,
            frame_count=frame_count,
            data_offset=sound_offset,
            data_size=sound_size,
            byte_order=byte_order,
            encoding=encoding,
            unsigned_8_bit=False,
        )
    except Exception:
        file.close()
        raise


def _validate_audio_format(
    channels: int,
    sample_rate: int,
    bits: int,
    block_align: int,
    encoding: str,
) -> None:
    valid_bits = {32, 64} if encoding == "float" else {8, 16, 24, 32}
    if bits not in valid_bits:
        raise ValueError("unsupported audio bit depth")
    if channels <= 0 or sample_rate <= 0:
        raise ValueError("invalid audio channel count or sample rate")
    if block_align != channels * (bits // 8):
        raise ValueError("packed or non-byte-aligned audio is unsupported")


def _decode_samples(
    raw: bytes,
    *,
    bits_per_sample: int,
    byte_order: str,
    encoding: str,
    unsigned_8_bit: bool,
) -> list[float]:
    endian = "<" if byte_order == "little" else ">"
    if encoding == "float":
        code = "f" if bits_per_sample == 32 else "d"
        width = bits_per_sample // 8
        return [value[0] for value in struct.iter_unpack(endian + code, raw[: len(raw) // width * width])]
    if bits_per_sample == 8:
        if unsigned_8_bit:
            return [(value - 128) / 128.0 for value in raw]
        return [struct.unpack("b", bytes((value,)))[0] / 128.0 for value in raw]
    if bits_per_sample == 16:
        return [value[0] / 32768.0 for value in struct.iter_unpack(endian + "h", raw)]
    if bits_per_sample == 32:
        return [value[0] / 2147483648.0 for value in struct.iter_unpack(endian + "i", raw)]
    byteorder_name = "little" if byte_order == "little" else "big"
    return [
        int.from_bytes(raw[index : index + 3], byteorder_name, signed=True) / 8388608.0
        for index in range(0, len(raw), 3)
    ]


def _decode_extended_80(raw: bytes) -> float:
    if len(raw) != 10:
        raise ValueError("invalid AIFF sample-rate field")
    exponent_word = int.from_bytes(raw[:2], "big")
    sign = -1.0 if exponent_word & 0x8000 else 1.0
    exponent = exponent_word & 0x7FFF
    mantissa = int.from_bytes(raw[2:], "big")
    if exponent == 0 and mantissa == 0:
        return 0.0
    if exponent == 0x7FFF:
        raise ValueError("invalid AIFF sample rate")
    return sign * mantissa * (2.0 ** (exponent - 16383 - 63))


def _channel_weights(channels: int, mask: int | None) -> tuple[list[float], str]:
    if mask:
        speaker_bits = [1 << bit for bit in range(32) if mask & (1 << bit)]
        if len(speaker_bits) == channels:
            # LFE is excluded; surround and rear channels receive +1.5 dB.
            front = {0x1, 0x2, 0x4}
            lfe = {0x8, 0x8000000}
            weights = [
                0.0 if speaker in lfe else (1.0 if speaker in front else 1.41)
                for speaker in speaker_bits
            ]
            return weights, "WAV channel mask was used for BS.1770 channel weighting."
    defaults = {
        1: [1.0],
        2: [1.0, 1.0],
        3: [1.0, 1.0, 1.0],
        4: [1.0, 1.0, 1.41, 1.41],
        5: [1.0, 1.0, 1.0, 1.41, 1.41],
        6: [1.0, 1.0, 1.0, 0.0, 1.41, 1.41],
    }
    if channels in defaults:
        note = (
            "Mono/stereo channel weighting is unambiguous."
            if channels <= 2
            else "No channel mask was available; standard channel order was assumed."
        )
        return defaults[channels], note
    return [1.0] * channels, "No channel mask was available; equal channel weighting was assumed."


def _integrated_loudness(block_energies: list[float]) -> float | None:
    absolute = [
        energy
        for energy in block_energies
        if _energy_to_lufs(energy) is not None
        and _energy_to_lufs(energy) >= _ABSOLUTE_GATE_LUFS
    ]
    if not absolute:
        return None
    relative_gate = _energy_to_lufs(sum(absolute) / len(absolute))
    if relative_gate is None:
        return None
    threshold = max(_ABSOLUTE_GATE_LUFS, relative_gate - 10.0)
    gated = [energy for energy in absolute if (_energy_to_lufs(energy) or -math.inf) >= threshold]
    if not gated:
        return None
    return _energy_to_lufs(sum(gated) / len(gated))


def _loudness_range(short_term_values: list[float | None]) -> float | None:
    absolute = [
        value for value in short_term_values if value is not None and value >= _ABSOLUTE_GATE_LUFS
    ]
    if not absolute:
        return None
    energies = [10.0 ** ((value - _LOUDNESS_OFFSET) / 10.0) for value in absolute]
    average_loudness = _energy_to_lufs(sum(energies) / len(energies))
    if average_loudness is None:
        return None
    threshold = max(_ABSOLUTE_GATE_LUFS, average_loudness - 20.0)
    gated = sorted(value for value in absolute if value >= threshold)
    if len(gated) < 2:
        return 0.0
    return _percentile(gated, 95.0) - _percentile(gated, 10.0)


def _energy_to_lufs(energy: float) -> float | None:
    if energy <= 0.0 or not math.isfinite(energy):
        return None
    return _LOUDNESS_OFFSET + 10.0 * math.log10(energy)


def _amplitude_to_dbfs(amplitude: float) -> float | None:
    if amplitude <= 0.0 or not math.isfinite(amplitude):
        return None
    return 20.0 * math.log10(amplitude)


def _finite_max(values: list[float | None]) -> float | None:
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return max(finite) if finite else None


def _percentile(values: list[float], percentage: float) -> float:
    position = (len(values) - 1) * percentage / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _rounded(value: float | None) -> float | None:
    return round(value, 2) if value is not None and math.isfinite(value) else None


def _build_analysis(
    measurements: dict[str, float | None],
    target_lufs: float | None,
    target_true_peak_dbtp: float,
) -> dict[str, Any]:
    integrated = measurements["integrated_lufs"]
    true_peak = measurements["true_peak_dbtp"]
    result: dict[str, Any] = {
        "target_lufs": target_lufs,
        "target_true_peak_dbtp": target_true_peak_dbtp if target_lufs is not None else None,
        "gain_to_target_db": None,
        "predicted_true_peak_dbtp": None,
        "peak_control_likely_required": None,
        "notes": [],
    }
    notes: list[str] = result["notes"]
    if integrated is None:
        notes.append("有効なIntegrated LUFSを算出できません。無音または0.4秒未満の可能性があります。")
        return result
    if target_lufs is None:
        notes.append("目標LUFSは未指定です。測定値を聴感とジャンルの意図に合わせて評価してください。")
        return result
    gain = target_lufs - integrated
    result["gain_to_target_db"] = round(gain, 2)
    if true_peak is not None:
        predicted = true_peak + gain
        result["predicted_true_peak_dbtp"] = round(predicted, 2)
        result["peak_control_likely_required"] = predicted > target_true_peak_dbtp
        if predicted > target_true_peak_dbtp:
            notes.append("単純なゲイン変更ではTrue Peak目標を超えるため、音質を確認しながらピーク制御が必要です。")
        else:
            notes.append("単純なゲイン変更後も推定True Peakは指定上限内です。")
    notes.append("数値合わせだけでなく、ラウドネスマッチしたA/B試聴で判断してください。")
    return result
