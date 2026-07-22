"""Tests for the unified ``abletongpt-cli`` dispatcher.

The dispatcher only routes ``<command> <rest...>`` to ``abletongpt.cli.<command>.main``
and adds no behaviour of its own. No Ableton, no network.
"""

from __future__ import annotations

import json

import pytest

from abletongpt.cli import main as unified
from abletongpt.cli.main import _SUBCOMMANDS, main


def test_every_subcommand_maps_to_a_real_delegate():
    for name, (handler, help_text) in _SUBCOMMANDS.items():
        module = __import__("abletongpt.cli.%s" % name, fromlist=["main"])
        assert handler is module.main
        assert help_text.strip()


def test_no_command_prints_help_and_returns_1(capsys):
    rc = main([])

    assert rc == 1
    out = capsys.readouterr().out
    assert "abletongpt-cli" in out
    for name in _SUBCOMMANDS:
        assert name in out


def test_top_level_help_lists_every_subcommand(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for name in _SUBCOMMANDS:
        assert name in out


def test_unknown_command_exits_2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["kazoo"])

    assert excinfo.value.code == 2
    assert "kazoo" in capsys.readouterr().err


def test_dispatches_compose_and_passes_arguments_through(capsys):
    rc = main(
        [
            "compose",
            "--title",
            "Demo",
            "--genre",
            "pop",
            "--mood",
            "bright",
            "--key",
            "C",
            "--mode",
            "major",
            "--tempo",
            "120",
            "--bars",
            "8",
            "--json",
        ]
    )

    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["title"] == "Demo"
    assert plan["tempo"] == 120


def test_subcommand_help_reaches_the_delegate(capsys):
    # ``compose --help`` must print the compose CLI's own help, not the dispatcher's.
    with pytest.raises(SystemExit) as excinfo:
        main(["compose", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--complexity" in out


def test_dispatches_contextual_subsubcommand(tmp_path, capsys):
    clip = tmp_path / "clip.json"
    clip.write_text(
        json.dumps(
            {
                "length_beats": 8.0,
                "notes": [
                    {"pitch": 60, "start_time": 0.0, "duration": 2.0, "velocity": 90},
                    {"pitch": 64, "start_time": 0.0, "duration": 2.0, "velocity": 90},
                    {"pitch": 67, "start_time": 0.0, "duration": 2.0, "velocity": 90},
                ],
            }
        ),
        encoding="utf-8",
    )

    rc = main(["contextual", "analyze", "--clip", str(clip), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True


def test_module_exposes_main_for_console_script():
    assert callable(unified.main)
