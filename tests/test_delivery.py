from __future__ import annotations

from pathlib import Path

import pytest

from abletongpt.delivery import (
    build_audio_export_manifest,
    verify_audio_export_report,
)


def _manifest(tmp_path: Path, **overrides):
    values = {
        "title": "Submerged Signal",
        "project_directory": str(tmp_path),
        "render_start_beats": 0.0,
        "render_length_beats": 256.0,
        "tempo": 122.0,
        "sample_rate_hz": 48000,
        "bit_depth": 24,
        "channels": 2,
        "normalize": False,
        "target_lufs": -7.5,
        "target_true_peak_dbtp": -1.0,
    }
    values.update(overrides)
    return build_audio_export_manifest(**values)


def _loudness_report(
    path: Path,
    *,
    duration: float = 125.902,
    sample_rate: int = 48000,
    bit_depth: int = 24,
    channels: int = 2,
    integrated_lufs: float = -9.85,
    sample_peak_dbfs: float = -1.3,
    true_peak_dbtp: float = -1.24,
):
    return {
        "file": {
            "path": str(path),
            "name": path.name,
            "container": "WAV",
            "sample_rate_hz": sample_rate,
            "channels": channels,
            "bit_depth": bit_depth,
            "duration_seconds": duration,
        },
        "measurements": {
            "integrated_lufs": integrated_lufs,
            "sample_peak_dbfs": sample_peak_dbfs,
            "true_peak_dbtp": true_peak_dbtp,
        },
        "standard": {
            "true_peak": "4x cubic inter-sample estimate; not a certified delivery meter"
        },
        "analysis_engine": {
            "name": "ffmpeg-ebur128",
            "accelerated": True,
            "fallback": False,
        },
    }


def test_build_manifest_records_manual_boundary_and_exact_live_settings(tmp_path: Path):
    manifest = _manifest(tmp_path)

    assert manifest["read_only"] is True
    assert manifest["manual_action_required"] is True
    assert manifest["live_api_boundary"]["save_live_set"] is False
    assert manifest["live_api_boundary"]["export_main_audio"] is False
    assert manifest["selection"]["render_start_display"] == "1.1.1"
    assert manifest["selection"]["render_length_display"] == "64.0.0"
    assert manifest["selection"]["expected_duration_seconds"] == 125.902
    assert manifest["format"] == {
        "file_type": "WAV",
        "extension": ".wav",
        "sample_rate_hz": 48000,
        "bit_depth": 24,
        "channels": 2,
        "convert_to_mono": False,
        "normalize": False,
        "dither": "None",
    }
    assert manifest["output"]["audio_path"] == str(tmp_path / "Submerged Signal.wav")
    assert any("Cmd+Shift+R" in step for step in manifest["manual_steps"])


def test_manifest_warns_about_normalize_and_existing_output(tmp_path: Path):
    existing = tmp_path / "Submerged Signal.wav"
    existing.write_bytes(b"old")

    manifest = _manifest(tmp_path, normalize=True)

    assert manifest["output"]["overwrite_requires_confirmation"] is True
    assert any("Normalize" in warning for warning in manifest["warnings"])
    assert any("already exists" in warning for warning in manifest["warnings"])


@pytest.mark.parametrize(
    "override,match",
    [
        ({"title": "../unsafe"}, "title"),
        ({"render_length_beats": 0.0}, "render_length_beats"),
        ({"render_length_beats": 4.1}, "sixteenth-note"),
        ({"tempo": 10.0}, "tempo"),
        ({"file_type": "mp3"}, "file_type"),
        ({"bit_depth": 20}, "bit_depth"),
        ({"channels": 6}, "channels"),
        ({"dither": "magic"}, "dither"),
    ],
)
def test_manifest_rejects_invalid_contracts(tmp_path: Path, override, match):
    with pytest.raises(ValueError, match=match):
        _manifest(tmp_path, **override)


def test_verify_export_passes_required_delivery_checks_and_warns_on_loudness(
    tmp_path: Path,
):
    manifest = _manifest(tmp_path)
    rendered = tmp_path / "Submerged Signal.wav"
    rendered.write_bytes(b"rendered")

    report = verify_audio_export_report(
        file_path=str(rendered),
        manifest=manifest,
        loudness_report=_loudness_report(rendered),
    )

    assert report["safe_to_deliver"] is True
    assert report["manual_reexport_required"] is False
    assert report["status"] == "warning"
    assert report["blocking_failures"] == []
    assert report["warnings"] == ["integrated_lufs"]
    assert report["measurements"]["true_peak_dbtp"] == -1.24
    assert report["analysis_engine"]["accelerated"] is True


def test_verify_export_fails_peak_duration_and_format_contracts(tmp_path: Path):
    manifest = _manifest(tmp_path)
    rendered = tmp_path / "Submerged Signal.wav"
    rendered.write_bytes(b"rendered")
    analysis = _loudness_report(
        rendered,
        duration=120.0,
        sample_rate=44100,
        true_peak_dbtp=0.05,
        sample_peak_dbfs=0.0,
    )

    report = verify_audio_export_report(
        file_path=str(rendered),
        manifest=manifest,
        loudness_report=analysis,
    )

    assert report["status"] == "fail"
    assert report["safe_to_deliver"] is False
    assert report["manual_reexport_required"] is True
    assert {"duration_seconds", "sample_rate_hz", "true_peak_dbtp"} <= set(
        report["blocking_failures"]
    )
    assert "normalization_or_zero_peak" in report["warnings"]
    assert any("Normalize" in note for note in report["guidance"])


def test_loudness_target_is_advisory_not_delivery_blocking(tmp_path: Path):
    manifest = _manifest(tmp_path, target_lufs=-7.5)
    rendered = tmp_path / "Submerged Signal.wav"
    rendered.write_bytes(b"rendered")
    analysis = _loudness_report(rendered, integrated_lufs=-14.0)

    report = verify_audio_export_report(
        file_path=str(rendered),
        manifest=manifest,
        loudness_report=analysis,
    )

    assert report["status"] == "warning"
    assert report["safe_to_deliver"] is True
    loudness_check = next(
        check for check in report["checks"] if check["name"] == "integrated_lufs"
    )
    assert loudness_check["blocking"] is False
