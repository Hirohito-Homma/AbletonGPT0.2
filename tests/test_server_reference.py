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


def test_compare_combines_loudness_and_tone(monkeypatch):
    monkeypatch.setattr(
        server, "analyze_loudness_file", lambda path, *a, **k: {"measurements": _LOUDNESS[path]}
    )
    monkeypatch.setattr(
        server, "extract_spectral_features", lambda path, *a, **k: {"features": _SPECTRAL[path]}
    )

    report = server.compare_mix_to_reference("mix.wav", "ref.wav")

    assert report["read_only"] is True
    assert report["deltas"]["loudness_lu"] == -4.0  # mix quieter
    assert report["deltas"]["brightness_hz"] == 1000.0  # mix brighter
    assert report["mix"]["file"] == "mix.wav"
    assert report["reference"]["file"] == "ref.wav"
    assert any("quieter" in note for note in report["guidance"])
    assert any("brighter" in note for note in report["guidance"])
