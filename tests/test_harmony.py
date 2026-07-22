"""Tests for Camelot-wheel key compatibility (pure, no Live, no NumPy)."""

from __future__ import annotations

import pytest

from abletongpt.harmony import (
    build_key_compatibility,
    camelot_code,
    parse_key,
    suggest_compatible_keys,
)


@pytest.mark.parametrize(
    "pc,mode,code",
    [
        (0, "major", "8B"),   # C major
        (9, "minor", "8A"),   # A minor (relative of C)
        (7, "major", "9B"),   # G major
        (5, "major", "7B"),   # F major
        (2, "minor", "7A"),   # D minor
        (11, "major", "1B"),  # B major
        (6, "major", "2B"),   # F# major
    ],
)
def test_camelot_code_known_positions(pc, mode, code):
    assert camelot_code(pc, mode) == code


def test_parse_key_accepts_all_notations():
    assert parse_key("C major") == (0, "major")
    assert parse_key("A minor") == (9, "minor")
    assert parse_key("C") == (0, "major")
    assert parse_key("Am") == (9, "minor")
    assert parse_key("F#m") == (6, "minor")
    assert parse_key("Db minor") == (1, "minor")  # flats accepted
    assert parse_key("8A") == (9, "minor")
    assert parse_key("8B") == (0, "major")
    assert parse_key("12b") == (4, "major")  # lowercase Camelot


def test_parse_key_rejects_garbage():
    for bad in ("", "H major", "C weird", "13A", "0B"):
        with pytest.raises(ValueError):
            parse_key(bad)


def test_identical_keys_score_100():
    report = build_key_compatibility("C major", "C major")
    assert report["read_only"] is True
    assert report["relationship"] == "identical"
    assert report["score"] == 100
    assert report["compatible"] is True
    assert report["a"]["camelot"] == "8B"


def test_relative_major_minor_is_highly_compatible():
    report = build_key_compatibility("C major", "A minor")
    assert report["relationship"] == "relative"
    assert report["camelot_distance"] == 0
    assert report["score"] >= 90
    assert report["compatible"] is True


def test_adjacent_fifth_is_compatible():
    report = build_key_compatibility("C major", "G major")  # 8B vs 9B
    assert report["relationship"] == "adjacent"
    assert report["camelot_distance"] == 1
    assert report["compatible"] is True


def test_two_step_is_energy_boost_borderline():
    report = build_key_compatibility("C major", "D major")  # 8B vs 10B
    assert report["relationship"] == "two-step"
    assert report["camelot_distance"] == 2
    assert report["compatible"] is False  # score 65 < 70


def test_distant_keys_clash():
    report = build_key_compatibility("C major", "F# major")  # 8B vs 2B, 6 apart
    assert report["relationship"] == "distant"
    assert report["camelot_distance"] == 6
    assert report["compatible"] is False
    assert report["score"] < 40


def test_camelot_input_matches_key_name_input():
    by_name = build_key_compatibility("C major", "G major")
    by_code = build_key_compatibility("8B", "9B")
    assert by_name["relationship"] == by_code["relationship"]
    assert by_name["score"] == by_code["score"]


def test_suggest_compatible_keys_returns_the_safe_ring():
    result = suggest_compatible_keys("A minor")  # 8A
    codes = {entry["camelot"] for entry in result["compatible"]}
    # same (8A), relative (8B), +1 (9A), -1 (7A)
    assert codes == {"8A", "8B", "9A", "7A"}
    relationships = {entry["relationship"] for entry in result["compatible"]}
    assert "identical" in relationships and "relative" in relationships


def test_suggest_wraps_around_the_wheel():
    result = suggest_compatible_keys("12B")  # up wraps to 1B, down to 11B
    codes = {entry["camelot"] for entry in result["compatible"]}
    assert codes == {"12B", "12A", "1B", "11B"}
