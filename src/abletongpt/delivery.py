from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable


_FILE_TYPES = {"wav": "WAV", "aiff": "AIFF"}
_DITHER_TYPES = {
    "none": "None",
    "triangular": "Triangular",
    "pow-r1": "POW-r 1",
    "pow-r2": "POW-r 2",
    "pow-r3": "POW-r 3",
}
_PLATFORMS = {"macos", "windows"}


class AudioVerificationCache:
    """Bounded process-local cache for immutable loudness-analysis results."""

    def __init__(self, max_entries: int = 8):
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
        self._lock = RLock()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def get_or_analyze(
        self,
        *,
        file_path: str,
        target_lufs: float | None,
        target_true_peak_dbtp: float,
        analyzer: Callable[..., dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return a cached report only when file identity and targets still match."""

        path = Path(file_path).expanduser().resolve()
        signature_before = _audio_file_signature(path)
        key = (
            str(path),
            signature_before["device"],
            signature_before["inode"],
            signature_before["size_bytes"],
            signature_before["modified_time_ns"],
            target_lufs,
            target_true_peak_dbtp,
        )
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return deepcopy(cached), self._cache_info(
                    hit=True,
                    path=path,
                    signature=signature_before,
                    target_lufs=target_lufs,
                    target_true_peak_dbtp=target_true_peak_dbtp,
                )

        report = analyzer(
            str(path),
            target_lufs=target_lufs,
            target_true_peak_dbtp=target_true_peak_dbtp,
        )
        signature_after = _audio_file_signature(path)
        if signature_after != signature_before:
            raise ValueError(
                "audio file changed during analysis; wait for export to finish and retry"
            )

        with self._lock:
            self._entries[key] = deepcopy(report)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return report, self._cache_info(
            hit=False,
            path=path,
            signature=signature_after,
            target_lufs=target_lufs,
            target_true_peak_dbtp=target_true_peak_dbtp,
        )

    def _cache_info(
        self,
        *,
        hit: bool,
        path: Path,
        signature: dict[str, int],
        target_lufs: float | None,
        target_true_peak_dbtp: float,
    ) -> dict[str, Any]:
        return {
            "hit": hit,
            "scope": "mcp-process",
            "max_entries": self.max_entries,
            "key": {
                "path": str(path),
                "size_bytes": signature["size_bytes"],
                "modified_time_ns": signature["modified_time_ns"],
                "target_lufs": target_lufs,
                "target_true_peak_dbtp": target_true_peak_dbtp,
            },
        }


def build_audio_export_manifest(
    *,
    title: str,
    project_directory: str,
    render_length_beats: float,
    tempo: float,
    render_start_beats: float = 0.0,
    beats_per_bar: int = 4,
    file_type: str = "wav",
    sample_rate_hz: int = 48000,
    bit_depth: int = 24,
    channels: int = 2,
    normalize: bool = False,
    dither: str = "none",
    target_lufs: float | None = None,
    target_true_peak_dbtp: float = -1.0,
    duration_tolerance_seconds: float = 0.25,
    loudness_tolerance_lu: float = 1.0,
    platform: str = "macos",
) -> dict[str, Any]:
    """Build a read-only handoff for Live's manual Save and Export dialogs.

    The public Live Object Model does not expose saving a Live Set or rendering
    the Main output. This manifest makes that boundary explicit and records the
    exact settings that :func:`verify_audio_export` will inspect afterwards.
    """

    clean_title = _validate_title(title)
    project_path = Path(project_directory).expanduser().resolve()
    length_beats = _finite_float(
        render_length_beats, "render_length_beats", minimum=0.000001
    )
    start_beats = _finite_float(
        render_start_beats, "render_start_beats", minimum=0.0
    )
    for value, name in (
        (start_beats, "render_start_beats"),
        (length_beats, "render_length_beats"),
    ):
        if abs(value * 4.0 - round(value * 4.0)) > 0.000001:
            raise ValueError(f"{name} must align to a sixteenth-note (0.25 beat) grid")
    tempo_bpm = _finite_float(tempo, "tempo", minimum=20.0, maximum=999.0)
    if not isinstance(beats_per_bar, int) or not 1 <= beats_per_bar <= 16:
        raise ValueError("beats_per_bar must be an integer between 1 and 16")

    normalized_file_type = str(file_type).strip().lower()
    if normalized_file_type == "aif":
        normalized_file_type = "aiff"
    if normalized_file_type not in _FILE_TYPES:
        raise ValueError("file_type must be wav or aiff")
    if not isinstance(sample_rate_hz, int) or not 8000 <= sample_rate_hz <= 384000:
        raise ValueError("sample_rate_hz must be an integer between 8000 and 384000")
    if bit_depth not in {16, 24, 32}:
        raise ValueError("bit_depth must be 16, 24, or 32")
    if channels not in {1, 2}:
        raise ValueError("channels must be 1 (mono) or 2 (stereo)")

    normalized_dither = str(dither).strip().lower().replace("_", "-")
    if normalized_dither not in _DITHER_TYPES:
        raise ValueError("dither must be none, triangular, pow-r1, pow-r2, or pow-r3")
    normalized_platform = str(platform).strip().lower()
    if normalized_platform not in _PLATFORMS:
        raise ValueError("platform must be macos or windows")
    if target_lufs is not None:
        target_lufs = _finite_float(
            target_lufs, "target_lufs", minimum=-36.0, maximum=-5.0
        )
    target_true_peak = _finite_float(
        target_true_peak_dbtp,
        "target_true_peak_dbtp",
        minimum=-9.0,
        maximum=0.0,
    )
    duration_tolerance = _finite_float(
        duration_tolerance_seconds,
        "duration_tolerance_seconds",
        minimum=0.001,
        maximum=10.0,
    )
    loudness_tolerance = _finite_float(
        loudness_tolerance_lu,
        "loudness_tolerance_lu",
        minimum=0.1,
        maximum=12.0,
    )

    extension = ".wav" if normalized_file_type == "wav" else ".aiff"
    audio_path = project_path / f"{clean_title}{extension}"
    live_set_path = project_path / f"{clean_title}.als"
    expected_duration = round(length_beats * 60.0 / tempo_bpm, 3)
    save_shortcut = "Cmd+S" if normalized_platform == "macos" else "Ctrl+S"
    export_shortcut = (
        "Cmd+Shift+R" if normalized_platform == "macos" else "Ctrl+Shift+R"
    )
    render_start_display = _live_start_display(start_beats, beats_per_bar)
    render_length_display = _live_length_display(length_beats, beats_per_bar)

    warnings: list[str] = []
    if normalize:
        warnings.append(
            "Normalize can raise the rendered peak to 0 dBFS; leave it Off for "
            "a peak-controlled master and verify the rendered file."
        )
    if bit_depth == 32 and normalized_dither != "none":
        warnings.append("Dither is normally unnecessary for a 32-bit export.")
    if audio_path.exists():
        warnings.append(
            "The planned audio path already exists; replacing it requires an "
            "explicit confirmation in Live's file dialog."
        )
    if live_set_path.exists():
        warnings.append(
            "The planned Live Set path already exists; Cmd+S updates that Set in place."
        )

    return {
        "read_only": True,
        "manual_action_required": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "live_api_boundary": {
            "save_live_set": False,
            "export_main_audio": False,
            "reason": (
                "The public Live Object Model exposes neither Live Set saving "
                "nor Main-output audio rendering."
            ),
        },
        "project": {
            "title": clean_title,
            "directory": str(project_path),
            "live_set_path": str(live_set_path),
            "live_set_exists": live_set_path.is_file(),
        },
        "selection": {
            "rendered_track": "Main",
            "render_start_beats": start_beats,
            "render_length_beats": length_beats,
            "beats_per_bar": beats_per_bar,
            "render_start_display": render_start_display,
            "render_length_display": render_length_display,
            "expected_duration_seconds": expected_duration,
        },
        "format": {
            "file_type": _FILE_TYPES[normalized_file_type],
            "extension": extension,
            "sample_rate_hz": sample_rate_hz,
            "bit_depth": bit_depth,
            "channels": channels,
            "convert_to_mono": channels == 1,
            "normalize": bool(normalize),
            "dither": _DITHER_TYPES[normalized_dither],
        },
        "output": {
            "audio_path": str(audio_path),
            "audio_exists": audio_path.is_file(),
            "overwrite_requires_confirmation": audio_path.exists(),
        },
        "verification": {
            "expected_audio_path": str(audio_path),
            "expected_file_type": _FILE_TYPES[normalized_file_type],
            "expected_sample_rate_hz": sample_rate_hz,
            "expected_bit_depth": bit_depth,
            "expected_channels": channels,
            "expected_duration_seconds": expected_duration,
            "duration_tolerance_seconds": duration_tolerance,
            "normalize": bool(normalize),
            "target_lufs": target_lufs,
            "loudness_tolerance_lu": loudness_tolerance,
            "target_true_peak_dbtp": target_true_peak,
        },
        "manual_steps": [
            f"Save the current Live Set with {save_shortcut} at {live_set_path}.",
            (
                "In Arrangement View select the intended range, then open Export "
                f"Audio/Video with {export_shortcut}."
            ),
            (
                f"Choose Main, Render Start {render_start_display}, and Render "
                f"Length {render_length_display}."
            ),
            (
                f"Choose {_FILE_TYPES[normalized_file_type]}, {sample_rate_hz} Hz, "
                f"{bit_depth}-bit, {'mono' if channels == 1 else 'stereo'}, "
                f"Normalize {'On' if normalize else 'Off'}, "
                f"Dither {_DITHER_TYPES[normalized_dither]}."
            ),
            f"Export to {audio_path}; confirm replacement only if that is intended.",
            "Run verify_audio_export with this manifest and the rendered file path.",
        ],
        "warnings": warnings,
    }


def verify_audio_export_report(
    *,
    file_path: str,
    manifest: dict[str, Any],
    loudness_report: dict[str, Any],
    analysis_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare an analyzed render to a manifest without modifying the file."""

    verification = manifest.get("verification")
    if not isinstance(verification, dict):
        raise ValueError("manifest must contain a verification object")
    file_info = loudness_report.get("file")
    measurements = loudness_report.get("measurements")
    if not isinstance(file_info, dict) or not isinstance(measurements, dict):
        raise ValueError("loudness_report must contain file and measurements objects")

    actual_path = Path(file_path).expanduser().resolve()
    if not actual_path.is_file():
        raise ValueError("audio file does not exist")

    checks: list[dict[str, Any]] = []

    def add_check(
        name: str,
        *,
        passed: bool,
        actual: Any,
        expected: Any,
        blocking: bool,
        note: str,
    ) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "blocking": bool(blocking),
                "actual": actual,
                "expected": expected,
                "note": note,
            }
        )

    expected_path = Path(str(verification["expected_audio_path"])).expanduser().resolve()
    add_check(
        "output_path",
        passed=actual_path == expected_path,
        actual=str(actual_path),
        expected=str(expected_path),
        blocking=False,
        note="A different path may be intentional, but should be confirmed.",
    )

    expected_file_type = str(verification["expected_file_type"])
    actual_file_type = str(file_info.get("container", "")).split("-", 1)[0]
    add_check(
        "file_type",
        passed=actual_file_type == expected_file_type,
        actual=actual_file_type,
        expected=expected_file_type,
        blocking=True,
        note="Container must match the export manifest.",
    )

    for key, check_name in (
        ("expected_sample_rate_hz", "sample_rate_hz"),
        ("expected_bit_depth", "bit_depth"),
        ("expected_channels", "channels"),
    ):
        expected = verification[key]
        actual = file_info.get(check_name)
        add_check(
            check_name,
            passed=actual == expected,
            actual=actual,
            expected=expected,
            blocking=True,
            note=f"{check_name} must match the delivery contract.",
        )

    expected_duration = float(verification["expected_duration_seconds"])
    duration_tolerance = float(verification["duration_tolerance_seconds"])
    actual_duration = float(file_info["duration_seconds"])
    duration_delta = round(actual_duration - expected_duration, 3)
    add_check(
        "duration_seconds",
        passed=abs(duration_delta) <= duration_tolerance,
        actual=actual_duration,
        expected={
            "value": expected_duration,
            "tolerance": duration_tolerance,
            "delta": duration_delta,
        },
        blocking=True,
        note="Duration verifies that the intended Arrangement range was rendered.",
    )

    target_true_peak = float(verification["target_true_peak_dbtp"])
    actual_true_peak = measurements.get("true_peak_dbtp")
    true_peak_passed = (
        actual_true_peak is not None and float(actual_true_peak) <= target_true_peak
    )
    add_check(
        "true_peak_dbtp",
        passed=true_peak_passed,
        actual=actual_true_peak,
        expected={"maximum": target_true_peak},
        blocking=True,
        note="Estimated True Peak must not exceed the planned ceiling.",
    )

    normalize_planned = bool(verification.get("normalize", False))
    sample_peak = measurements.get("sample_peak_dbfs")
    suspicious_zero_peak = (
        not normalize_planned
        and sample_peak is not None
        and float(sample_peak) >= -0.05
    )
    add_check(
        "normalization_or_zero_peak",
        passed=not suspicious_zero_peak,
        actual=sample_peak,
        expected="below -0.05 dBFS when Normalize is Off",
        blocking=False,
        note="A zero peak can indicate normalization or clipping.",
    )

    target_lufs = verification.get("target_lufs")
    if target_lufs is not None:
        actual_lufs = measurements.get("integrated_lufs")
        tolerance_lu = float(verification["loudness_tolerance_lu"])
        loudness_delta = (
            None
            if actual_lufs is None
            else round(float(actual_lufs) - float(target_lufs), 2)
        )
        add_check(
            "integrated_lufs",
            passed=loudness_delta is not None and abs(loudness_delta) <= tolerance_lu,
            actual=actual_lufs,
            expected={
                "target": target_lufs,
                "tolerance_lu": tolerance_lu,
                "delta_lu": loudness_delta,
            },
            blocking=False,
            note=(
                "Loudness is an artistic/format target, not a reason to raise gain "
                "past the True Peak ceiling."
            ),
        )

    blocking_failures = [
        check["name"] for check in checks if check["blocking"] and not check["passed"]
    ]
    warning_failures = [
        check["name"] for check in checks if not check["blocking"] and not check["passed"]
    ]
    status = "fail" if blocking_failures else "warning" if warning_failures else "pass"
    guidance: list[str] = []
    if "duration_seconds" in blocking_failures:
        guidance.append(
            "ArrangementのRender Start／Lengthを確認して再書き出ししてください。"
        )
    if "true_peak_dbtp" in blocking_failures:
        guidance.append(
            "NormalizeをOffにし、必要ならゲインまたはリミッターでTrue Peakを抑えてください。"
        )
    if {
        "file_type",
        "sample_rate_hz",
        "bit_depth",
        "channels",
    } & set(blocking_failures):
        guidance.append("書き出し形式をmanifestと一致させてください。")
    if "integrated_lufs" in warning_failures:
        guidance.append(
            "LUFSだけを合わせず、ラウドネスマッチしたA/B試聴とTrue Peakを優先してください。"
        )
    if "output_path" in warning_failures:
        guidance.append("書き出し先とファイル名が意図したものか確認してください。")
    if "normalization_or_zero_peak" in warning_failures:
        guidance.append("NormalizeがOffか、0 dBFSクリップがないか確認してください。")
    if status == "pass":
        guidance.append("書き出しはmanifestの必須条件を満たしています。")

    stat = actual_path.stat()
    return {
        "read_only": True,
        "status": status,
        "safe_to_deliver": not blocking_failures,
        "manual_reexport_required": bool(blocking_failures),
        "file": {
            **file_info,
            "path": str(actual_path),
            "size_bytes": stat.st_size,
            "modified_at_utc": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        },
        "measurements": measurements,
        "analysis_engine": loudness_report.get("analysis_engine"),
        "analysis_cache": analysis_cache,
        "checks": checks,
        "blocking_failures": blocking_failures,
        "warnings": warning_failures,
        "guidance": guidance,
        "true_peak_note": loudness_report.get("standard", {}).get("true_peak"),
    }


def _audio_file_signature(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise ValueError("audio file does not exist")
    stat = path.stat()
    return {
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size_bytes": stat.st_size,
        "modified_time_ns": stat.st_mtime_ns,
    }


def _validate_title(title: str) -> str:
    clean = str(title).strip()
    if not clean:
        raise ValueError("title must not be empty")
    if clean in {".", ".."} or Path(clean).name != clean or "/" in clean or "\\" in clean:
        raise ValueError("title must be a file name without directory separators")
    return clean


def _finite_float(
    value: float,
    name: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if converted != converted or converted in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be finite")
    if converted < minimum or (maximum is not None and converted > maximum):
        if maximum is None:
            raise ValueError(f"{name} must be at least {minimum}")
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return converted


def _live_start_display(beats: float, beats_per_bar: int) -> str:
    sixteenths = round(beats * 4.0)
    bar_sixteenths = beats_per_bar * 4
    bar = sixteenths // bar_sixteenths + 1
    remainder = sixteenths % bar_sixteenths
    beat = remainder // 4 + 1
    subdivision = remainder % 4 + 1
    return f"{bar}.{beat}.{subdivision}"


def _live_length_display(beats: float, beats_per_bar: int) -> str:
    sixteenths = round(beats * 4.0)
    bar_sixteenths = beats_per_bar * 4
    bars = sixteenths // bar_sixteenths
    remainder = sixteenths % bar_sixteenths
    beat = remainder // 4
    subdivision = remainder % 4
    return f"{bars}.{beat}.{subdivision}"
