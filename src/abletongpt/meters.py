"""Turn Live's momentary master meter into a peak/headroom check against a target.

Pure logic, stdlib only -- no Live connection and no NumPy. The server tool samples the master
track's ``output_meter_level`` (Live's momentary/hold peak meter, a 0..1 float -- **not** LUFS)
over a short window while the set plays, and hands the samples plus a built-in target profile
(:mod:`abletongpt.targets`) to :func:`build_live_headroom_report`.

Honest scope: a momentary peak meter can only report what meters measure -- peak level and how
much headroom is left under a target's true-peak ceiling. It cannot yield a calibrated BS.1770
loudness (LUFS) reading (that needs K-weighting + gated integration over the whole render), so the
target's ``integrated_lufs`` is shown for reference only, with the average meter level as an
uncalibrated loudness *proxy* and a pointer to the offline ``compare_mix_to_target`` path for a
real LUFS comparison. Live's 0..1 meter scale is not documented as linear, so the dBFS values here
are treated as ``20*log10(level)`` and flagged ``approximate``.
"""

from __future__ import annotations

import math
from typing import Any

_FLOOR_DBFS = -120.0

# Gaps (dB) below which the headroom situation is called "on target" rather than flagged.
_HEADROOM_TOLERANCE_DB = 0.5


def meter_level_to_dbfs(level: float | None) -> float | None:
    """Map a 0..1 ``output_meter_level`` to approximate dBFS (``1.0`` -> ``0`` dBFS).

    Live's meter scale is not documented as linear, so this treats the reading as linear
    amplitude and is a rough peak indicator, not a calibrated measurement. Returns ``None`` for
    ``None`` input and a fixed floor for zero/negative levels.
    """
    if level is None:
        return None
    level = float(level)
    if level <= 0.0:
        return _FLOOR_DBFS
    if level >= 1.0:
        return 0.0
    return round(20.0 * math.log10(level), 2)


def summarize_meter_samples(samples: list[float | None]) -> dict[str, Any] | None:
    """Reduce a window of meter readings to peak/mean level + dBFS, or ``None`` if all empty."""
    levels = [float(value) for value in samples if value is not None]
    if not levels:
        return None
    peak_level = max(levels)
    mean_level = sum(levels) / len(levels)
    return {
        "samples": len(levels),
        "peak_level": round(peak_level, 4),
        "mean_level": round(mean_level, 4),
        "peak_dbfs": meter_level_to_dbfs(peak_level),
        "mean_dbfs": meter_level_to_dbfs(mean_level),
    }


_CALIBRATION_NOTE = (
    "output_meter_level is Live's momentary peak meter (0..1), treated here as linear amplitude "
    "-- a rough peak/headroom check, not a calibrated LUFS measurement. For a loudness (LUFS) "
    "comparison to the target, bounce the master and use compare_mix_to_target."
)


def build_live_headroom_report(
    samples: list[float | None],
    target: dict[str, Any],
) -> dict[str, Any]:
    """Compare a window of master meter samples against a target's true-peak ceiling.

    ``target`` is a profile from :mod:`abletongpt.targets` (carries ``true_peak_dbtp`` and
    ``integrated_lufs``). The report leads with peak headroom (what a meter can actually measure)
    and treats the average meter level only as an uncalibrated loudness proxy.
    """
    target_view = {
        "name": target.get("target"),
        "description": target.get("description"),
        "true_peak_dbtp": target.get("true_peak_dbtp"),
        "integrated_lufs": target.get("integrated_lufs"),
    }

    meter = summarize_meter_samples(samples)
    if meter is None:
        return {
            "read_only": True,
            "approximate": True,
            "meter": None,
            "target": target_view,
            "peak_headroom_db": None,
            "guidance": [
                "No meter reading was available -- make sure the set is playing and the "
                "Remote Script backend is in use (the Extensions SDK exposes no meter)."
            ],
            "note": _CALIBRATION_NOTE,
        }

    guidance: list[str] = []
    ceiling = target_view["true_peak_dbtp"]
    peak_dbfs = meter["peak_dbfs"]

    headroom = None
    if ceiling is not None and peak_dbfs is not None:
        headroom = round(float(ceiling) - peak_dbfs, 2)
        if headroom < -_HEADROOM_TOLERANCE_DB:
            guidance.append(
                "Peaks reach %.1f dBFS, %.1f dB above the %s target ceiling (%.1f dBTP) -- "
                "pull the master level down or add limiting."
                % (peak_dbfs, -headroom, target_view["name"], ceiling)
            )
        elif headroom > _HEADROOM_TOLERANCE_DB:
            guidance.append(
                "Peaks reach %.1f dBFS, %.1f dB of headroom under the %s target ceiling "
                "(%.1f dBTP)." % (peak_dbfs, headroom, target_view["name"], ceiling)
            )
        else:
            guidance.append(
                "Peaks sit right at the %s target ceiling (%.1f dBTP)."
                % (target_view["name"], ceiling)
            )

    lufs = target_view["integrated_lufs"]
    if lufs is not None and meter["mean_dbfs"] is not None:
        guidance.append(
            "Average meter level is %.1f dBFS (uncalibrated loudness proxy); the %s target is "
            "%.1f LUFS. dBFS and LUFS use different references -- bounce and use "
            "compare_mix_to_target for a real loudness gap."
            % (meter["mean_dbfs"], target_view["name"], lufs)
        )

    if not guidance:
        guidance.append("Metered peaks captured; no target ceiling to compare against.")

    return {
        "read_only": True,
        "approximate": True,
        "meter": meter,
        "target": target_view,
        "peak_headroom_db": headroom,
        "guidance": guidance,
        "note": _CALIBRATION_NOTE,
    }
