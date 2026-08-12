from __future__ import annotations

from abletongpt import server
from abletongpt.delivery import AudioVerificationCache


def test_plan_audio_export_is_read_only_and_does_not_probe_live(tmp_path, monkeypatch):
    class NoLiveBridge:
        def call(self, *_args, **_kwargs):
            raise AssertionError("planning an export must not call Live")

    monkeypatch.setattr(server, "bridge", NoLiveBridge())

    manifest = server.plan_audio_export(
        title="Submerged Signal",
        project_directory=str(tmp_path),
        render_length_beats=256.0,
        tempo=122.0,
        target_lufs=-7.5,
    )

    assert manifest["read_only"] is True
    assert manifest["manual_action_required"] is True
    assert manifest["selection"]["expected_duration_seconds"] == 125.902
    assert manifest["verification"]["target_lufs"] == -7.5


def test_verify_audio_export_analyzes_once_then_applies_manifest(tmp_path, monkeypatch):
    manifest = {
        "verification": {
            "target_lufs": -9.0,
            "target_true_peak_dbtp": -1.0,
        }
    }
    loudness = {"file": {}, "measurements": {}}
    expected = {"read_only": True, "status": "pass"}
    calls = []
    cache_results = []

    def fake_analyze(path, target_lufs=None, target_true_peak_dbtp=-1.0):
        calls.append((path, target_lufs, target_true_peak_dbtp))
        return loudness

    def fake_verify(*, file_path, manifest, loudness_report, analysis_cache):
        assert file_path == str(rendered)
        assert manifest["verification"]["target_lufs"] == -9.0
        assert loudness_report == loudness
        cache_results.append(analysis_cache)
        return {**expected, "analysis_cache": analysis_cache}

    rendered = tmp_path / "mix.wav"
    rendered.write_bytes(b"rendered")
    monkeypatch.setattr(server, "_audio_verification_cache", AudioVerificationCache())
    monkeypatch.setattr(server, "analyze_loudness_file", fake_analyze)
    monkeypatch.setattr(server, "verify_audio_export_report", fake_verify)

    first = server.verify_audio_export(str(rendered), manifest)
    second = server.verify_audio_export(str(rendered), manifest)

    assert first["analysis_cache"]["hit"] is False
    assert second["analysis_cache"]["hit"] is True
    assert len(calls) == 1
    assert calls[0][1:] == (-9.0, -1.0)
    assert [result["hit"] for result in cache_results] == [False, True]


def test_wait_for_audio_export_waits_then_verifies(monkeypatch):
    manifest = {"verification": {}}
    watch = {
        "read_only": True,
        "path": "/tmp/mix.wav",
        "change_detected": True,
    }
    verification = {"read_only": True, "status": "pass"}
    calls = []

    def fake_wait(path, **options):
        calls.append(("wait", path, options))
        return watch

    def fake_verify(*, file_path, manifest):
        calls.append(("verify", file_path, manifest))
        return verification

    monkeypatch.setattr(server, "wait_for_stable_audio_file", fake_wait)
    monkeypatch.setattr(server, "verify_audio_export", fake_verify)

    result = server.wait_for_audio_export(
        "/tmp/mix.wav",
        manifest,
        timeout_seconds=30.0,
        poll_interval_seconds=0.25,
        stable_seconds=1.0,
        require_change=True,
    )

    assert result == {**verification, "export_watch": watch}
    assert calls[0][0] == "wait"
    assert calls[0][2]["require_change"] is True
    assert calls[1] == ("verify", "/tmp/mix.wav", manifest)


def test_wait_for_audio_export_rejects_invalid_manifest_before_waiting(monkeypatch):
    def fail_wait(*_args, **_kwargs):
        raise AssertionError("invalid manifest must fail before waiting")

    monkeypatch.setattr(server, "wait_for_stable_audio_file", fail_wait)

    try:
        server.wait_for_audio_export("/tmp/mix.wav", {})
    except ValueError as error:
        assert "verification object" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_capabilities_describe_manual_export_boundary_and_verification():
    capabilities = server.get_abletongpt_capabilities()

    assert any("export manifests" in feature for feature in capabilities["features"])
    assert any(
        "explicit user actions" in rule for rule in capabilities["safety"]
    )
