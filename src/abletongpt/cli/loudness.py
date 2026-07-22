"""Command-line entry point for offline loudness analysis of WAV/AIFF files.

    python -m abletongpt.cli.loudness --file master.wav
    python -m abletongpt.cli.loudness --file master.wav --target-lufs -14
    python -m abletongpt.cli.loudness --file master.aiff --json

Read-only: this measures the file (BS.1770 / EBU R128) and prints the result -- as a
human summary, or the full report as JSON with ``--json``. It never writes or modifies
the audio. Wraps the pure :func:`abletongpt.loudness.analyze_loudness_file` engine.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..loudness import analyze_loudness_file


def _num(value: object, suffix: str = "") -> str:
    """Render a measurement, or ``n/a`` when it is undefined (e.g. silence)."""
    if value is None:
        return "n/a"
    return "%g%s" % (value, suffix)


def _print_result(result: dict, *, as_json: bool) -> None:
    """Print a loudness report as JSON or a human-readable summary."""
    if as_json:
        # ensure_ascii=False keeps the Japanese quality/analysis notes readable.
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return

    file = result["file"]
    m = result["measurements"]
    analysis = result["analysis"]
    print(
        "file: %s  (%s, %g Hz, %g-bit, %gch, %gs)"
        % (
            file["name"],
            file["container"],
            file["sample_rate_hz"],
            file["bit_depth"],
            file["channels"],
            file["duration_seconds"],
        )
    )
    print(
        "integrated: %s LUFS   range: %s LU"
        % (_num(m["integrated_lufs"]), _num(m["loudness_range_lu"]))
    )
    print(
        "true peak:  %s dBTP   sample peak: %s dBFS"
        % (_num(m["true_peak_dbtp"]), _num(m["sample_peak_dbfs"]))
    )
    print(
        "rms: %s dBFS   crest: %s dB"
        % (_num(m["rms_dbfs"]), _num(m["crest_factor_db"]))
    )
    if analysis.get("target_lufs") is not None:
        print(
            "target: %g LUFS -> gain %s dB   peak control: %s"
            % (
                analysis["target_lufs"],
                _num(analysis["gain_to_target_db"]),
                "yes" if analysis["peak_control_likely_required"] else "no",
            )
        )


def _cmd_analyze(args: argparse.Namespace) -> int:
    try:
        result = analyze_loudness_file(
            args.file,
            target_lufs=args.target_lufs,
            target_true_peak_dbtp=args.target_true_peak,
        )
    except (ValueError, OSError) as exc:
        # Missing file, unsupported format, or an out-of-range target -> clean exit 2
        # rather than a traceback.
        print("loudness: %s" % exc, file=sys.stderr)
        return 2
    _print_result(result, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m abletongpt.cli.loudness",
        description="Analyze the loudness of a WAV/AIFF file offline (read-only).",
    )
    parser.add_argument(
        "--file", required=True, help="Path to a WAV or AIFF file to analyze."
    )
    parser.add_argument(
        "--target-lufs",
        type=float,
        default=None,
        metavar="LUFS",
        help="Target integrated loudness (-36..-5); adds gain-to-target guidance.",
    )
    parser.add_argument(
        "--target-true-peak",
        type=float,
        default=-1.0,
        metavar="DBTP",
        help="Target true-peak ceiling in dBTP (-9..0, default: %(default)s).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full analysis report as machine-readable JSON on stdout.",
    )
    parser.set_defaults(func=_cmd_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 on an invalid request)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CLI
    raise SystemExit(main())
