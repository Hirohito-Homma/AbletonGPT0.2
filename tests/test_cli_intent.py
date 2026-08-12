from __future__ import annotations

import json

from abletongpt.cli.intent import main


def test_intent_infers_a_song_spec_yaml(capsys):
    rc = main([
        "110 BPM、D# minor。Mutation Funk、Dub、Tech Houseのハイブリッド。5分くらい。",
    ])

    assert rc == 0
    out = capsys.readouterr().out
    assert "version: 0.1" in out
    assert "tempo: 110.0" in out or "tempo: 110" in out
    assert "key: D#" in out or "key: D# minor" in out
    assert "arrangement:" in out


def test_intent_json_is_machine_readable_and_derived_from_prompt(capsys):
    rc = main([
        "--json",
        "120 BPM, C major, pop and uplifting, 8 bars",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == "0.1"
    assert payload["tempo"] == 120.0
    assert payload["bars"] == 8
    assert payload["genre"] == "pop"
    assert payload["mood"] == "uplifting"


def test_intent_title_override_wins(capsys):
    rc = main(["--title", "Demo Spec", "110 BPM, bright pop", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Demo Spec"