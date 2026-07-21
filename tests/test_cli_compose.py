"""Tests for the ``compose`` song-sketch CLI.

The CLI wraps the pure ``build_song_plan`` engine: no files, no Ableton. These tests
cover the human and ``--json`` output plus argument validation.
"""

from __future__ import annotations

import json

import pytest

from abletongpt.cli.compose import main


_BASE = [
    "--title", "Demo",
    "--genre", "pop",
    "--mood", "bright",
    "--key", "C",
    "--mode", "major",
    "--tempo", "120",
    "--bars", "8",
]


def test_compose_human_output_summarizes_tracks(capsys):
    rc = main([*_BASE, "--seed", "7"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "title: Demo" in out
    assert "key: C major" in out
    # Every part of the sketch is listed.
    for role in ("chords", "bass", "melody", "drums"):
        assert role in out


def test_compose_json_is_machine_readable_and_deterministic(capsys):
    rc = main([*_BASE, "--seed", "7", "--json"])
    assert rc == 0
    first = json.loads(capsys.readouterr().out)

    rc2 = main([*_BASE, "--seed", "7", "--json"])
    assert rc2 == 0
    second = json.loads(capsys.readouterr().out)

    assert first["title"] == "Demo"
    assert first["bars"] == 8
    assert [t["role"] for t in first["tracks"]] == ["chords", "bass", "melody", "drums"]
    # Same seed -> identical plan (deterministic engine).
    assert first == second


def test_compose_complexity_changes_chord_voicing(capsys):
    main([*_BASE, "--complexity", "triad", "--json"])
    triad = json.loads(capsys.readouterr().out)
    main([*_BASE, "--complexity", "ninth", "--json"])
    ninth = json.loads(capsys.readouterr().out)

    triad_chords = next(t for t in triad["tracks"] if t["role"] == "chords")
    ninth_chords = next(t for t in ninth["tracks"] if t["role"] == "chords")
    # Ninth voicings stack more tones than triads.
    assert len(ninth_chords["notes"]) > len(triad_chords["notes"])


def test_compose_rejects_out_of_range_tempo(capsys):
    rc = main(
        [
            "--title", "X",
            "--genre", "pop",
            "--mood", "bright",
            "--key", "C",
            "--mode", "major",
            "--tempo", "999",
            "--bars", "8",
        ]
    )

    assert rc == 2
    assert "tempo must be between" in capsys.readouterr().err


def test_compose_rejects_invalid_key_via_argparse():
    with pytest.raises(SystemExit):
        main(
            [
                "--title", "X",
                "--genre", "pop",
                "--mood", "bright",
                "--key", "H",  # not a valid pitch class
                "--mode", "major",
                "--tempo", "120",
                "--bars", "8",
            ]
        )
