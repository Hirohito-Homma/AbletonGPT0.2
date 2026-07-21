"""Tests for the ``instruments`` planning CLI.

The CLI is a thin wrapper over the pure ``build_instrument_plan`` engine: no files,
no Ableton. These tests exercise the human and ``--json`` output and the argument
validation argparse enforces via ``choices``.
"""

from __future__ import annotations

import json

import pytest

from abletongpt.cli.instruments import main


def test_plan_human_output_lists_selected_instruments(capsys):
    rc = main(["--genre", "edm", "--mood", "uplifting", "--roles", "bass", "drums"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "genre: edm" in out
    assert "mood: uplifting" in out
    # One line per requested role, each naming the chosen instrument.
    assert "bass" in out
    assert "drums" in out


def test_plan_json_is_machine_readable(capsys):
    rc = main(
        ["--genre", "pop", "--mood", "bright", "--edition", "standard", "--json"]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["genre"] == "pop"
    assert payload["mood"] == "bright"
    assert payload["live_edition"] == "standard"
    # Default roles when --roles is omitted: chords, bass, melody, drums.
    assert [s["role"] for s in payload["selections"]] == [
        "chords",
        "bass",
        "melody",
        "drums",
    ]
    # The plan-only contract is present and confirmation-gated.
    assert payload["apply_contract"]["requires_confirmation"] is True


def test_plan_respects_requested_roles(capsys):
    rc = main(
        ["--genre", "lofi", "--mood", "chill", "--roles", "keys", "bass", "--json"]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [s["role"] for s in payload["selections"]] == ["keys", "bass"]


def test_plan_rejects_unknown_genre():
    # argparse enforces --genre choices, exiting (code 2) before the engine runs.
    with pytest.raises(SystemExit):
        main(["--genre", "house", "--mood", "chill"])


def test_plan_rejects_unknown_role():
    with pytest.raises(SystemExit):
        main(["--genre", "edm", "--mood", "dark", "--roles", "sub"])
