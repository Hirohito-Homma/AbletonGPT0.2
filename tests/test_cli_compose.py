"""Tests for the ``compose`` song-sketch CLI.

The CLI wraps the pure ``build_song_plan`` engine: no files, no Ableton. These tests
cover the human and ``--json`` output plus argument validation.
"""

from __future__ import annotations

import json

import pytest

from abletongpt.cli.compose import main
from abletongpt.composition import build_song_plan


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
    assert first["song_spec"]["version"] == "0.1"
    assert first["song_spec"]["tracks"][1]["role"] == "bass"
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


def test_compose_spec_yaml_exposes_a_human_editable_song_spec(capsys):
    rc = main([*_BASE, "--seed", "7", "--spec-yaml"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "version: 0.1" in out
    assert "title: Demo" in out
    assert "tracks:" in out
    assert "role: bass" in out


def test_compose_supports_64_bar_song_sketches(capsys):
    rc = main([
        "--title", "Long Demo",
        "--genre", "pop",
        "--mood", "bright",
        "--key", "C",
        "--mode", "major",
        "--tempo", "120",
        "--bars", "64",
        "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bars"] == 64
    assert payload["song_spec"]["bars"] == 64


def test_compose_cli_accepts_songspec_style_genre_alias(capsys):
    rc = main([
        "--title", "Demo",
        "--genre", "dub_techno",
        "--mood", "bright",
        "--key", "C",
        "--mode", "major",
        "--tempo", "120",
        "--bars", "8",
        "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["genre"] == "dub_techno"
    assert payload["song_spec"]["genre"] == "dub_techno"
    assert payload["professional_settings"]["requested_genre"] == "dub_techno"


@pytest.mark.parametrize("genre", ["tech_house", "dub_techno"])
def test_build_song_plan_normalizes_songspec_style_genres(genre):
    plan = build_song_plan("Demo", genre, "bright", "C", "major", 120, 8)

    assert plan["genre"] == genre
    assert plan["professional_settings"]["requested_genre"] == genre
