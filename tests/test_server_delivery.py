from __future__ import annotations

from abletongpt import server


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


def test_verify_audio_export_analyzes_once_then_applies_manifest(monkeypatch):
    manifest = {
        "verification": {
            "target_lufs": -9.0,
            "target_true_peak_dbtp": -1.0,
        }
    }
    loudness = {"file": {}, "measurements": {}}
    expected = {"read_only": True, "status": "pass"}
    calls = []

    def fake_analyze(path, target_lufs=None, target_true_peak_dbtp=-1.0):
        calls.append((path, target_lufs, target_true_peak_dbtp))
        return loudness

    def fake_verify(*, file_path, manifest, loudness_report):
        assert file_path == "mix.wav"
        assert manifest["verification"]["target_lufs"] == -9.0
        assert loudness_report is loudness
        return expected

    monkeypatch.setattr(server, "analyze_loudness_file", fake_analyze)
    monkeypatch.setattr(server, "verify_audio_export_report", fake_verify)

    assert server.verify_audio_export("mix.wav", manifest) is expected
    assert calls == [("mix.wav", -9.0, -1.0)]


def test_capabilities_describe_manual_export_boundary_and_verification():
    capabilities = server.get_abletongpt_capabilities()

    assert any("export manifests" in feature for feature in capabilities["features"])
    assert any(
        "explicit user actions" in rule for rule in capabilities["safety"]
    )
