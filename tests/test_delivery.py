from __future__ import annotations

from pathlib import Path

import pytest

from abletongpt.delivery import (
    AudioVerificationCache,
    build_audio_export_manifest,
    verify_audio_export_report,
    wait_for_stable_audio_file,
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


def test_verification_cache_reuses_unchanged_file_and_returns_copies(tmp_path: Path):
    rendered = tmp_path / "mix.wav"
    rendered.write_bytes(b"first render")
    cache = AudioVerificationCache(max_entries=2)
    calls = []

    def analyze(path, **targets):
        calls.append((path, targets))
        return {"file": {"path": path}, "measurements": {"integrated_lufs": -9.0}}

    first, first_cache = cache.get_or_analyze(
        file_path=str(rendered),
        target_lufs=-9.0,
        target_true_peak_dbtp=-1.0,
        analyzer=analyze,
    )
    first["measurements"]["integrated_lufs"] = 0.0
    second, second_cache = cache.get_or_analyze(
        file_path=str(rendered),
        target_lufs=-9.0,
        target_true_peak_dbtp=-1.0,
        analyzer=analyze,
    )

    assert len(calls) == 1
    assert first_cache["hit"] is False
    assert second_cache["hit"] is True
    assert second["measurements"]["integrated_lufs"] == -9.0
    assert second_cache["key"]["size_bytes"] == len(b"first render")


def test_verification_cache_invalidates_changed_file_or_targets(tmp_path: Path):
    rendered = tmp_path / "mix.wav"
    rendered.write_bytes(b"first")
    cache = AudioVerificationCache()
    calls = []

    def analyze(path, **targets):
        calls.append((path, targets))
        return {"file": {"path": path}, "measurements": {}}

    cache.get_or_analyze(
        file_path=str(rendered),
        target_lufs=-9.0,
        target_true_peak_dbtp=-1.0,
        analyzer=analyze,
    )
    rendered.write_bytes(b"second render")
    _, changed_file = cache.get_or_analyze(
        file_path=str(rendered),
        target_lufs=-9.0,
        target_true_peak_dbtp=-1.0,
        analyzer=analyze,
    )
    _, changed_target = cache.get_or_analyze(
        file_path=str(rendered),
        target_lufs=-14.0,
        target_true_peak_dbtp=-1.0,
        analyzer=analyze,
    )

    assert len(calls) == 3
    assert changed_file["hit"] is False
    assert changed_target["hit"] is False


def test_verification_cache_rejects_file_changed_during_analysis(tmp_path: Path):
    rendered = tmp_path / "mix.wav"
    rendered.write_bytes(b"incomplete")
    cache = AudioVerificationCache()

    def analyze(path, **_targets):
        Path(path).write_bytes(b"completed export")
        return {"file": {"path": path}, "measurements": {}}

    with pytest.raises(ValueError, match="changed during analysis"):
        cache.get_or_analyze(
            file_path=str(rendered),
            target_lufs=-9.0,
            target_true_peak_dbtp=-1.0,
            analyzer=analyze,
        )


def test_wait_for_stable_audio_file_detects_creation_and_completion(tmp_path: Path):
    rendered = tmp_path / "mix.wav"
    clock = [0.0]

    def monotonic():
        return clock[0]

    def sleeper(seconds):
        clock[0] += seconds
        if clock[0] == 0.5:
            rendered.write_bytes(b"partial")
        elif clock[0] == 1.0:
            rendered.write_bytes(b"completed export")

    result = wait_for_stable_audio_file(
        str(rendered),
        timeout_seconds=3.0,
        poll_interval_seconds=0.5,
        stable_seconds=1.0,
        monotonic=monotonic,
        sleeper=sleeper,
    )

    assert result["file_created"] is True
    assert result["signature"]["size_bytes"] == len(b"completed export")
    assert result["waited_seconds"] == 2.0
    assert result["read_only"] is True


def test_wait_for_stable_audio_file_can_require_existing_file_to_change(
    tmp_path: Path,
):
    rendered = tmp_path / "mix.wav"
    rendered.write_bytes(b"old export")
    clock = [0.0]

    def monotonic():
        return clock[0]

    def sleeper(seconds):
        clock[0] += seconds
        if clock[0] == 1.0:
            rendered.write_bytes(b"replacement export")

    result = wait_for_stable_audio_file(
        str(rendered),
        timeout_seconds=3.0,
        poll_interval_seconds=0.5,
        stable_seconds=0.5,
        require_change=True,
        monotonic=monotonic,
        sleeper=sleeper,
    )

    assert result["file_created"] is False
    assert result["change_detected"] is True
    assert result["require_change"] is True
    assert result["waited_seconds"] == 1.5


def test_wait_for_stable_audio_file_times_out_without_required_change(
    tmp_path: Path,
):
    rendered = tmp_path / "mix.wav"
    rendered.write_bytes(b"unchanged")
    clock = [0.0]

    def monotonic():
        return clock[0]

    def sleeper(seconds):
        clock[0] += seconds

    with pytest.raises(TimeoutError, match="new or changed"):
        wait_for_stable_audio_file(
            str(rendered),
            timeout_seconds=1.0,
            poll_interval_seconds=0.25,
            stable_seconds=0.5,
            require_change=True,
            monotonic=monotonic,
            sleeper=sleeper,
        )


def test_wait_for_stable_audio_file_does_not_accept_empty_placeholder(
    tmp_path: Path,
):
    rendered = tmp_path / "mix.wav"
    rendered.write_bytes(b"")
    clock = [0.0]

    def monotonic():
        return clock[0]

    def sleeper(seconds):
        clock[0] += seconds

    with pytest.raises(TimeoutError, match="stable audio export"):
        wait_for_stable_audio_file(
            str(rendered),
            timeout_seconds=0.5,
            poll_interval_seconds=0.1,
            stable_seconds=0.2,
            monotonic=monotonic,
            sleeper=sleeper,
        )


def test_wait_for_stable_audio_file_validates_windows(tmp_path: Path):
    with pytest.raises(ValueError, match="stable_seconds"):
        wait_for_stable_audio_file(
            str(tmp_path / "mix.wav"),
            timeout_seconds=1.0,
            stable_seconds=2.0,
        )
