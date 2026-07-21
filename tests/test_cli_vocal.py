"""Tests for the ``vocal`` planning CLI.

The CLI wraps the pure ``build_vocal_plan`` engine: no files, no Ableton. These tests
cover the human and ``--json`` output plus the validation (argparse choices and the
engine's own rules).
"""

from __future__ import annotations

import json

import pytest

from abletongpt.cli.vocal import main


_BASE = [
    "--title", "Neon",
    "--lyrics", "la la shine on",
    "--genre", "pop",
    "--mood", "bright",
    "--key", "A",
    "--mode", "minor",
    "--tempo", "120",
    "--bars", "8",
]


def test_plan_human_output_summarizes_guide(capsys):
    rc = main([*_BASE, "--seed", "7"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "title: Neon" in out
    assert "key: A minor" in out
    assert "vocal events:" in out
    # The first lyric syllable appears in the event preview.
    assert "la" in out


def test_plan_json_is_machine_readable_and_deterministic(capsys):
    rc = main([*_BASE, "--seed", "7", "--json"])
    assert rc == 0
    first = json.loads(capsys.readouterr().out)

    rc2 = main([*_BASE, "--seed", "7", "--json"])
    assert rc2 == 0
    second = json.loads(capsys.readouterr().out)

    assert first["title"] == "Neon"
    assert first["key"] == "A minor"
    assert first["language_hint"] == "en"
    assert len(first["vocal_events"]) == len(first["midi_notes"]) > 0
    # Same seed -> identical plan (deterministic engine).
    assert first == second


def test_plan_rejects_empty_lyrics(capsys):
    rc = main(
        [
            "--title", "X",
            "--lyrics", "   ",
            "--genre", "pop",
            "--mood", "bright",
            "--key", "A",
            "--mode", "minor",
            "--tempo", "120",
            "--bars", "8",
        ]
    )

    assert rc == 2
    assert "lyrics must not be empty" in capsys.readouterr().err


def test_plan_rejects_out_of_range_tempo(capsys):
    rc = main(
        [
            "--title", "X",
            "--lyrics", "la la",
            "--genre", "pop",
            "--mood", "bright",
            "--key", "A",
            "--mode", "minor",
            "--tempo", "999",
            "--bars", "8",
        ]
    )

    assert rc == 2
    assert "tempo must be between" in capsys.readouterr().err


def test_plan_rejects_invalid_bars_via_argparse():
    # --bars 7 is not an allowed choice, so argparse exits before the engine runs.
    with pytest.raises(SystemExit):
        main(
            [
                "--title", "X",
                "--lyrics", "la la",
                "--genre", "pop",
                "--mood", "bright",
                "--key", "A",
                "--mode", "minor",
                "--tempo", "120",
                "--bars", "7",
            ]
        )
