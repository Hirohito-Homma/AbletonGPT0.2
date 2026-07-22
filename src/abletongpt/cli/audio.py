"""Command-line entry point for offline audio-track feature extraction.

    python -m abletongpt.cli.audio tempo --file loop.wav
    python -m abletongpt.cli.audio tempo --file loop.wav --min-bpm 80 --max-bpm 160 --json
    python -m abletongpt.cli.audio key --file loop.wav
    python -m abletongpt.cli.audio key --file loop.wav --json
    python -m abletongpt.cli.audio chords --file loop.wav
    python -m abletongpt.cli.audio chords --file loop.wav --window-seconds 0.25 --json
    python -m abletongpt.cli.audio melody --file lead.wav
    python -m abletongpt.cli.audio melody --file lead.wav --min-f0 110 --max-f0 880 --json
    python -m abletongpt.cli.audio onsets --file loop.wav
    python -m abletongpt.cli.audio onsets --file loop.wav --delta 0.05 --json
    python -m abletongpt.cli.audio beats --file loop.wav
    python -m abletongpt.cli.audio beats --file loop.wav --beats-per-bar 3 --json
    python -m abletongpt.cli.audio spectral --file pad.wav
    python -m abletongpt.cli.audio spectral --file pad.wav --rolloff-percent 0.95 --json
    python -m abletongpt.cli.audio bands --file mix.wav
    python -m abletongpt.cli.audio structure --file song.wav
    python -m abletongpt.cli.audio structure --file song.wav --window-seconds 0.5 --json

Read-only: measures the file and prints the result -- a human summary, or the full result
as JSON with ``--json``. It never writes or modifies the audio. Wraps the pure
:mod:`abletongpt.audio` engine, which needs the optional ``audio`` extra (NumPy);
install it with ``pip install abletongpt[audio]``. Subcommands grow as extractors are
added.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..audio import (
    AudioDependencyError,
    detect_onsets,
    estimate_chords,
    estimate_key,
    estimate_tempo,
    extract_melody,
    extract_spectral_bands,
    extract_spectral_features,
    segment_structure,
    track_beats,
)


def _print_tempo(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "tempo: %g BPM  (confidence %.2f)   %g s @ %d Hz   range %g-%g   [%s]"
        % (
            result["tempo_bpm"],
            result["confidence"],
            result["duration_seconds"],
            result["sample_rate"],
            result["bpm_range"][0],
            result["bpm_range"][1],
            result["method"],
        )
    )


def _print_key(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "key: %s  (confidence %.2f)   alt %s (%.2f)   %g s @ %d Hz   [%s]"
        % (
            result["key"],
            result["confidence"],
            result["alternative_key"],
            result["alternative_confidence"],
            result["duration_seconds"],
            result["sample_rate"],
            result["method"],
        )
    )


def _cmd_tempo(args: argparse.Namespace) -> int:
    try:
        result = estimate_tempo(args.file, min_bpm=args.min_bpm, max_bpm=args.max_bpm)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_tempo(result, as_json=args.json)
    return 0


def _print_chords(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "progression: %s   (%g s @ %d Hz, %g s windows)   [%s]"
        % (
            " ".join(result["progression"]) or "(none)",
            result["duration_seconds"],
            result["sample_rate"],
            result["window_seconds"],
            result["method"],
        )
    )
    for segment in result["chords"]:
        print(
            "  %6.2f - %6.2f s  %-4s  (%.2f)"
            % (
                segment["start_seconds"],
                segment["end_seconds"],
                segment["chord"],
                segment["confidence"],
            )
        )


def _cmd_key(args: argparse.Namespace) -> int:
    try:
        result = estimate_key(args.file)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_key(result, as_json=args.json)
    return 0


def _print_melody(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "melody: %s   (%g s @ %d Hz, %g Hz-%g Hz)   [%s]"
        % (
            " ".join(result["note_names"]) or "(none)",
            result["duration_seconds"],
            result["sample_rate"],
            result["f0_range_hz"][0],
            result["f0_range_hz"][1],
            result["method"],
        )
    )
    for note in result["notes"]:
        print(
            "  %6.2f - %6.2f s  %-4s (MIDI %3d)  (%.2f)"
            % (
                note["start_seconds"],
                note["end_seconds"],
                note["note"],
                note["midi"],
                note["confidence"],
            )
        )


def _cmd_chords(args: argparse.Namespace) -> int:
    try:
        result = estimate_chords(args.file, window_seconds=args.window_seconds)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_chords(result, as_json=args.json)
    return 0


def _print_onsets(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "onsets: %d   (%g s @ %d Hz)   [%s]"
        % (
            result["onset_count"],
            result["duration_seconds"],
            result["sample_rate"],
            result["method"],
        )
    )
    for onset in result["onsets"]:
        print("  %8.3f s   (strength %.2f)" % (onset["time_seconds"], onset["strength"]))


def _cmd_melody(args: argparse.Namespace) -> int:
    try:
        result = extract_melody(args.file, min_f0=args.min_f0, max_f0=args.max_f0)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_melody(result, as_json=args.json)
    return 0


def _print_beats(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "beats: %d @ %g BPM  (confidence %.2f)   %g s @ %d Hz   %d/bar   [%s]"
        % (
            result["beat_count"],
            result["tempo_bpm"],
            result["tempo_confidence"],
            result["duration_seconds"],
            result["sample_rate"],
            result["beats_per_bar"],
            result["method"],
        )
    )
    bar_starts = set(result["bar_start_times"])
    for beat in result["beats"]:
        marker = "|" if beat["time_seconds"] in bar_starts else " "
        print("  %s %8.3f s   (strength %.2f)" % (marker, beat["time_seconds"], beat["strength"]))


def _cmd_onsets(args: argparse.Namespace) -> int:
    try:
        result = detect_onsets(args.file, delta=args.delta)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_onsets(result, as_json=args.json)
    return 0


def _print_spectral(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "spectral features: %d frames   (%g s @ %d Hz)   [%s]"
        % (
            result["frames_analyzed"],
            result["duration_seconds"],
            result["sample_rate"],
            result["method"],
        )
    )
    for name, stats in result["features"].items():
        print(
            "  %-22s mean %10.4g   std %10.4g   [%g .. %g]"
            % (name, stats["mean"], stats["std"], stats["min"], stats["max"])
        )


def _cmd_beats(args: argparse.Namespace) -> int:
    try:
        result = track_beats(args.file, beats_per_bar=args.beats_per_bar)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_beats(result, as_json=args.json)
    return 0


def _print_structure(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "structure: %d sections   (%g s @ %d Hz)   [%s]"
        % (
            result["segment_count"],
            result["duration_seconds"],
            result["sample_rate"],
            result["method"],
        )
    )
    for segment in result["segments"]:
        print(
            "  %s   %8.3f - %8.3f s"
            % (segment["label"], segment["start_seconds"], segment["end_seconds"])
        )


def _cmd_spectral(args: argparse.Namespace) -> int:
    try:
        result = extract_spectral_features(args.file, rolloff_percent=args.rolloff_percent)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_spectral(result, as_json=args.json)
    return 0


def _print_bands(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print(
        "band balance:   (%g s @ %d Hz)   [%s]"
        % (result["duration_seconds"], result["sample_rate"], result["method"])
    )
    for band in result["bands"]:
        bar = "#" * int(round(band["fraction"] * 40))
        print(
            "  %-9s %5.0f-%-5.0f Hz  %5.1f%%  %s"
            % (band["name"], band["low_hz"], band["high_hz"], band["fraction"] * 100, bar)
        )


def _cmd_bands(args: argparse.Namespace) -> int:
    try:
        result = extract_spectral_bands(args.file)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_bands(result, as_json=args.json)
    return 0


def _cmd_structure(args: argparse.Namespace) -> int:
    try:
        result = segment_structure(args.file, window_seconds=args.window_seconds)
    except AudioDependencyError as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print("audio: %s" % exc, file=sys.stderr)
        return 2
    _print_structure(result, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.audio",
        description="Offline audio-track feature extraction (no Ableton needed).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    tempo = sub.add_parser("tempo", help="Estimate the tempo (BPM) of an audio file.")
    tempo.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    tempo.add_argument(
        "--min-bpm", type=float, default=60.0, dest="min_bpm", help="Lowest BPM to consider."
    )
    tempo.add_argument(
        "--max-bpm", type=float, default=200.0, dest="max_bpm", help="Highest BPM to consider."
    )
    tempo.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    tempo.set_defaults(func=_cmd_tempo)

    key = sub.add_parser("key", help="Estimate the musical key of an audio file.")
    key.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    key.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    key.set_defaults(func=_cmd_key)

    chords = sub.add_parser("chords", help="Extract a chord progression from an audio file.")
    chords.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    chords.add_argument(
        "--window-seconds",
        type=float,
        default=0.5,
        dest="window_seconds",
        help="Analysis window length in seconds (chord time resolution).",
    )
    chords.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    chords.set_defaults(func=_cmd_chords)

    melody = sub.add_parser("melody", help="Extract a monophonic melody from an audio file.")
    melody.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    melody.add_argument(
        "--min-f0", type=float, default=65.0, dest="min_f0", help="Lowest pitch to track (Hz)."
    )
    melody.add_argument(
        "--max-f0", type=float, default=1047.0, dest="max_f0", help="Highest pitch to track (Hz)."
    )
    melody.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    melody.set_defaults(func=_cmd_melody)

    onsets = sub.add_parser("onsets", help="Detect note/transient onset times in an audio file.")
    onsets.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    onsets.add_argument(
        "--delta",
        type=float,
        default=0.07,
        help="Peak-picking sensitivity threshold in [0,1); lower detects more onsets.",
    )
    onsets.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    onsets.set_defaults(func=_cmd_onsets)

    beats = sub.add_parser("beats", help="Track the beat grid (beat times) of an audio file.")
    beats.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    beats.add_argument(
        "--beats-per-bar",
        type=int,
        default=4,
        dest="beats_per_bar",
        help="Group beats into bars of this many (assumes the first beat is a downbeat).",
    )
    beats.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    beats.set_defaults(func=_cmd_beats)

    spectral = sub.add_parser("spectral", help="Extract timbral spectral features from an audio file.")
    spectral.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    spectral.add_argument(
        "--rolloff-percent",
        type=float,
        default=0.85,
        dest="rolloff_percent",
        help="Energy fraction for the spectral rolloff frequency (0-1).",
    )
    spectral.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    spectral.set_defaults(func=_cmd_spectral)

    bands = sub.add_parser("bands", help="Show the tonal band balance of an audio file.")
    bands.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    bands.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    bands.set_defaults(func=_cmd_bands)

    structure = sub.add_parser("structure", help="Segment an audio file into sections.")
    structure.add_argument("--file", required=True, help="Path to a WAV/AIFF file.")
    structure.add_argument(
        "--window-seconds",
        type=float,
        default=1.0,
        dest="window_seconds",
        help="Analysis window length in seconds (structure time resolution).",
    )
    structure.add_argument("--json", action="store_true", help="Emit the full result as JSON.")
    structure.set_defaults(func=_cmd_structure)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 bad request, 3 missing extra)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
