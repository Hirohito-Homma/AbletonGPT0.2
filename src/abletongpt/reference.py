"""Compare a mix against a reference track and give mixing guidance.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_reference_comparison`
takes two flat audio *profiles* (loudness + tone numbers already extracted by the server
tool from :mod:`abletongpt.loudness` and :mod:`abletongpt.audio`) and reports the differences
plus plain-language guidance ("your mix is 2 LU quieter and brighter than the reference").
Deterministic and read-only; it never decides gain changes for you, only describes the gap.
"""

from __future__ import annotations

from typing import Any

# Difference thresholds above which a gap is worth mentioning in the guidance.
_LOUDNESS_LU = 1.0
_RANGE_LU = 2.0
_CREST_DB = 1.5
_TRUE_PEAK_DB = 0.5
_BRIGHTNESS_RATIO = 0.1  # 10% relative centroid difference
_BAND_FRACTION = 0.03  # 3 percentage points of band-energy share


def _delta(mix_value: float | None, reference_value: float | None) -> float | None:
    if mix_value is None or reference_value is None:
        return None
    return round(float(mix_value) - float(reference_value), 4)


def build_reference_comparison(
    mix: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    """Compare two audio profiles (``mix`` minus ``reference``) and return guidance.

    Each profile carries ``integrated_lufs``, ``loudness_range_lu``, ``true_peak_dbtp``,
    ``crest_factor_db``, ``centroid_hz`` and ``rolloff_hz`` (any may be ``None``). Deltas are
    mix-minus-reference, so a positive loudness delta means the mix is louder.
    """
    deltas = {
        "loudness_lu": _delta(mix.get("integrated_lufs"), reference.get("integrated_lufs")),
        "loudness_range_lu": _delta(mix.get("loudness_range_lu"), reference.get("loudness_range_lu")),
        "true_peak_db": _delta(mix.get("true_peak_dbtp"), reference.get("true_peak_dbtp")),
        "crest_factor_db": _delta(mix.get("crest_factor_db"), reference.get("crest_factor_db")),
        "brightness_hz": _delta(mix.get("centroid_hz"), reference.get("centroid_hz")),
        "rolloff_hz": _delta(mix.get("rolloff_hz"), reference.get("rolloff_hz")),
    }

    guidance: list[str] = []

    loudness = deltas["loudness_lu"]
    if loudness is not None and abs(loudness) >= _LOUDNESS_LU:
        louder = "louder" if loudness > 0 else "quieter"
        guidance.append("Mix is %.1f LU %s than the reference." % (abs(loudness), louder))

    lra = deltas["loudness_range_lu"]
    if lra is not None and abs(lra) >= _RANGE_LU:
        wider = "wider" if lra > 0 else "narrower"
        guidance.append(
            "Mix has a %s loudness range (%.1f LU) -- %s dynamics than the reference."
            % (wider, abs(lra), "more" if lra > 0 else "less")
        )

    crest = deltas["crest_factor_db"]
    if crest is not None and abs(crest) >= _CREST_DB:
        guidance.append(
            "Mix crest factor is %.1f dB %s -- it is %s than the reference."
            % (abs(crest), "higher" if crest > 0 else "lower", "punchier/less compressed" if crest > 0 else "more compressed")
        )

    true_peak = deltas["true_peak_db"]
    if true_peak is not None and abs(true_peak) >= _TRUE_PEAK_DB:
        guidance.append(
            "Mix true peak is %.1f dB %s than the reference."
            % (abs(true_peak), "higher" if true_peak > 0 else "lower")
        )

    brightness = deltas["brightness_hz"]
    reference_centroid = reference.get("centroid_hz")
    if brightness is not None and reference_centroid:
        if abs(brightness) >= _BRIGHTNESS_RATIO * float(reference_centroid):
            guidance.append(
                "Mix is spectrally %s (centroid %+.0f Hz vs the reference)."
                % ("brighter" if brightness > 0 else "darker", brightness)
            )

    # Per-band tonal balance, when both profiles carry band fractions.
    mix_bands = mix.get("bands")
    reference_bands = reference.get("bands")
    if isinstance(mix_bands, dict) and isinstance(reference_bands, dict):
        band_deltas: dict[str, float] = {}
        for name, mix_fraction in mix_bands.items():
            if name not in reference_bands:
                continue
            band_delta = round(float(mix_fraction) - float(reference_bands[name]), 4)
            band_deltas[name] = band_delta
            if abs(band_delta) >= _BAND_FRACTION:
                guidance.append(
                    "Mix has %s %s energy than the reference (%+.1f%% of the balance)."
                    % ("more" if band_delta > 0 else "less", name.replace("_", " "), band_delta * 100)
                )
        deltas["bands"] = band_deltas

    if not guidance:
        guidance.append("Mix and reference are closely matched on the measured metrics.")

    return {
        "read_only": True,
        "mix": mix,
        "reference": reference,
        "deltas": deltas,
        "guidance": guidance,
    }
