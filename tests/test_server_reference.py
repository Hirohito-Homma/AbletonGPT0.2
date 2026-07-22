"""Test the compare_mix_to_reference server tool.

Read-only: it runs loudness + spectral analysis on both files and compares them. The two
NumPy/file analyzers are monkeypatched with canned results keyed by path -- no audio file.
"""

from __future__ import annotations

from abletongpt import server


_LOUDNESS = {
    "mix.wav": {"integrated_lufs": -16.0, "loudness_range_lu": 5.0, "true_peak_dbtp": -1.0, "crest_factor_db": 10.0},
    "ref.wav": {"integrated_lufs": -12.0, "loudness_range_lu": 8.0, "true_peak_dbtp": -0.5, "crest_factor_db": 13.0},
}
_SPECTRAL = {
    "mix.wav": {"spectral_centroid_hz": {"mean": 3000.0}, "spectral_rolloff_hz": {"mean": 8000.0}},
    "ref.wav": {"spectral_centroid_hz": {"mean": 2000.0}, "spectral_rolloff_hz": {"mean": 6000.0}},
}
_BANDS = {
    "mix.wav": {"band_fractions": {"low": 0.30, "low_mid": 0.2, "mid": 0.2, "high_mid": 0.2, "high": 0.10}},
    "ref.wav": {"band_fractions": {"low": 0.20, "low_mid": 0.2, "mid": 0.2, "high_mid": 0.2, "high": 0.20}},
}
_STEREO = {
    "mix.wav": {"width_side_ratio": 0.40, "correlation": 0.5},
    "ref.wav": {"width_side_ratio": 0.20, "correlation": 0.9},
}


def test_compare_combines_loudness_tone_bands_and_stereo(monkeypatch):
    monkeypatch.setattr(
        server, "analyze_loudness_file", lambda path, *a, **k: {"measurements": _LOUDNESS[path]}
    )
    monkeypatch.setattr(
        server, "extract_spectral_features", lambda path, *a, **k: {"features": _SPECTRAL[path]}
    )
    monkeypatch.setattr(server, "extract_spectral_bands", lambda path, *a, **k: dict(_BANDS[path]))
    monkeypatch.setattr(server, "analyze_stereo_field", lambda path, *a, **k: dict(_STEREO[path]))

    report = server.compare_mix_to_reference("mix.wav", "ref.wav")

    assert report["read_only"] is True
    assert report["deltas"]["loudness_lu"] == -4.0  # mix quieter
    assert report["deltas"]["brightness_hz"] == 1000.0  # mix brighter
    assert report["deltas"]["bands"]["low"] == 0.1  # mix has more low end
    assert report["deltas"]["stereo_width"] == 0.2  # mix wider
    assert report["mix"]["file"] == "mix.wav"
    assert report["reference"]["file"] == "ref.wav"
    assert any("quieter" in note for note in report["guidance"])
    assert any("brighter" in note for note in report["guidance"])
    assert any("more low energy" in note for note in report["guidance"])
    assert any("wider" in note for note in report["guidance"])
    # A single summary score across all measured dimensions.
    assert 0.0 <= report["match"]["score"] <= 100.0
    assert report["match"]["weakest_dimension"] in report["match"]["dimensions"]


def test_list_mix_targets_returns_the_builtin_targets():
    result = server.list_mix_targets()

    assert result["read_only"] is True
    names = {row["name"] for row in result["targets"]}
    assert {"streaming", "modern-pop", "edm", "classical"} <= names


def test_compare_mix_to_target_uses_builtin_profile(monkeypatch):
    monkeypatch.setattr(
        server, "analyze_loudness_file", lambda path, *a, **k: {"measurements": _LOUDNESS[path]}
    )
    monkeypatch.setattr(
        server, "extract_spectral_features", lambda path, *a, **k: {"features": _SPECTRAL[path]}
    )
    monkeypatch.setattr(server, "extract_spectral_bands", lambda path, *a, **k: dict(_BANDS[path]))
    monkeypatch.setattr(server, "analyze_stereo_field", lambda path, *a, **k: dict(_STEREO[path]))

    report = server.compare_mix_to_target("mix.wav", "edm")

    assert report["read_only"] is True
    assert report["reference"]["target"] == "edm"
    # mix.wav is -16 LUFS vs the -7.5 EDM target -> 8.5 LU quieter.
    assert report["deltas"]["loudness_lu"] == -8.5
    assert any("quieter" in note for note in report["guidance"])
    assert 0.0 <= report["match"]["score"] <= 100.0


def test_compare_mix_to_target_unknown_returns_error_and_list(monkeypatch):
    # An unknown target short-circuits before any audio analysis runs.
    def _boom(*a, **k):
        raise AssertionError("audio analysis should not run for an unknown target")

    monkeypatch.setattr(server, "analyze_loudness_file", _boom)

    result = server.compare_mix_to_target("mix.wav", "dubstep")

    assert result["read_only"] is True
    assert "dubstep" in result["error"]
    assert {row["name"] for row in result["targets"]}
