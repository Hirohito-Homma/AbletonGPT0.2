"""Test the harmonic key-compatibility server tools (no Live, estimate_key monkeypatched)."""

from __future__ import annotations

from abletongpt import server


def test_analyze_key_compatibility_reports_relationship():
    report = server.analyze_key_compatibility("C major", "A minor")
    assert report["relationship"] == "relative"
    assert report["score"] >= 90


def test_analyze_key_compatibility_bad_input_returns_error():
    report = server.analyze_key_compatibility("C major", "H flat")
    assert report["read_only"] is True
    assert "error" in report


def test_suggest_harmonic_keys_lists_the_ring():
    result = server.suggest_harmonic_keys("8A")
    codes = {entry["camelot"] for entry in result["compatible"]}
    assert codes == {"8A", "8B", "9A", "7A"}


def test_analyze_audio_key_compatibility_runs_estimate_on_both(monkeypatch):
    keys = {
        "a.wav": {"key": "C major", "confidence": 0.9},
        "b.wav": {"key": "G major", "confidence": 0.7},
    }
    monkeypatch.setattr(server, "estimate_key", lambda path, *a, **k: dict(keys[path]))

    report = server.analyze_audio_key_compatibility("a.wav", "b.wav")

    assert report["a"]["camelot"] == "8B"
    assert report["b"]["camelot"] == "9B"
    assert report["relationship"] == "adjacent"
    assert report["a"]["confidence"] == 0.9
    assert report["b"]["confidence"] == 0.7
