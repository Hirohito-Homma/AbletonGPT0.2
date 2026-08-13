"""Decide the frequency-band and stereo treatment each song section should get.

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_section_spectral_plan`
takes a song structure, reads the narrative arc for it (:func:`narrative.build_narrative_arc`, so it
reuses the same energy/archetype reading), and for every section works out how the mix should be
shaped in the frequency domain and across the stereo field:

* a per-band **EQ move** (``gain_db`` for low / low_mid / mid / high_mid / high) -- e.g. a
  high-passed, airy intro; a low-shelved, mid-focused breakdown; a full-spectrum chorus;
* the resulting **band balance** (five fractions summing to 1.0, directly comparable to the
  built-in :mod:`targets` genre profiles and to :func:`audio.extract_spectral_bands`);
* a **stereo width** (0..1) blended with the section's energy, plus a ``low_mono`` recommendation
  (keep the low end mono for translation) that depends on how much low energy the section carries.

Report-only and deterministic: Live's API exposes no way to *automate* per-section EQ/width across
the arrangement timeline through the bridge, so this reports the decision (like the offline
``reference``/``targets`` mixing tools) rather than applying it. The five-band model and the neutral
baseline are the same ones used across the mixing tools, so the numbers line up.
"""

from __future__ import annotations

import math
from typing import Any

from .narrative import build_narrative_arc

BANDS = ("low", "low_mid", "mid", "high_mid", "high")

# Neutral full-range reference balance -- the ``streaming`` target from :mod:`targets` (fractions
# sum to 1.0). Per-section balances are this baseline scaled by the archetype's band multipliers.
_NEUTRAL_BALANCE: dict[str, float] = {
    "low": 0.28,
    "low_mid": 0.30,
    "mid": 0.26,
    "high_mid": 0.11,
    "high": 0.05,
}

# Per-archetype spectral/stereo intent. ``bands`` are relative multipliers around the neutral
# baseline (>1 emphasise, <1 reduce); ``width`` is the base stereo width (0..1) before the energy
# blend. Together they tell the per-section frequency/stereo story: a filtered intro, an opening
# build, a full wide chorus, an intimate narrow breakdown.
_ARCHETYPE_SPECTRAL: dict[str, dict[str, Any]] = {
    "intro": {
        "bands": {"low": 0.40, "low_mid": 0.70, "mid": 1.10, "high_mid": 1.20, "high": 1.20},
        "width": 0.50,
    },
    "verse": {
        "bands": {"low": 0.90, "low_mid": 1.00, "mid": 1.05, "high_mid": 0.95, "high": 0.90},
        "width": 0.55,
    },
    "build": {
        "bands": {"low": 0.80, "low_mid": 0.90, "mid": 1.00, "high_mid": 1.15, "high": 1.25},
        "width": 0.60,
    },
    "chorus": {
        "bands": {"low": 1.20, "low_mid": 1.10, "mid": 1.00, "high_mid": 1.05, "high": 1.15},
        "width": 0.90,
    },
    "bridge": {
        "bands": {"low": 0.85, "low_mid": 1.00, "mid": 1.20, "high_mid": 1.00, "high": 0.90},
        "width": 0.60,
    },
    "breakdown": {
        "bands": {"low": 0.50, "low_mid": 1.10, "mid": 1.15, "high_mid": 0.90, "high": 0.70},
        "width": 0.40,
    },
    "outro": {
        "bands": {"low": 0.60, "low_mid": 0.90, "mid": 1.00, "high_mid": 1.00, "high": 0.95},
        "width": 0.50,
    },
}

# A section keeps its low end mono only when it carries meaningful low energy (heavily high-passed
# sections have little sub to worry about).
_LOW_MONO_THRESHOLD = 0.55

# EQ moves are clamped to a musical +/- range (this is a mix decision, not surgical correction).
_MAX_GAIN_DB = 6.0


def _gain_db(multiplier: float) -> float:
    """Convert a band multiplier to a clamped dB move (1.0 -> 0 dB)."""
    if multiplier <= 0:
        return -_MAX_GAIN_DB
    db = 20.0 * math.log10(multiplier)
    return round(max(-_MAX_GAIN_DB, min(_MAX_GAIN_DB, db)), 1)


def _treatment(gain_db: float) -> str:
    if gain_db >= 1.0:
        return "boost"
    if gain_db <= -1.0:
        return "cut"
    return "neutral"


def _normalized_balance(gains: dict[str, float]) -> dict[str, float]:
    """The balance that the *reported* EQ moves produce.

    Derived from the clamped ``gain_db`` rather than the archetype's raw
    multiplier, because those disagree wherever the clamp bites: the intro asks
    for 0.40x on the low band, which is -7.96 dB, and the report offers -6 dB.
    Reading the balance off the raw multiplier described a cut deeper than the
    one it told you to make.
    """

    scaled = {band: _NEUTRAL_BALANCE[band] * (10.0 ** (gains[band] / 20.0)) for band in BANDS}
    total = sum(scaled.values()) or 1.0
    balance = {band: round(scaled[band] / total, 4) for band in BANDS}
    # Rounding five fractions independently loses up to 5e-5 of the whole, and
    # these are compared against `targets.py` profiles that do sum to 1.0. The
    # residual goes on the largest band, where it is smallest in relative terms.
    largest = max(BANDS, key=lambda band: balance[band])
    balance[largest] = round(balance[largest] + (1.0 - sum(balance.values())), 4)
    return balance


def _width_label(width: float) -> str:
    if width < 0.35:
        return "narrow"
    if width < 0.70:
        return "moderate"
    return "wide"


def _advice(label: str, archetype: str, gains: dict[str, float], width_label: str, low_mono: bool) -> str:
    """A short Japanese one-liner: the dominant band move + the stereo intent."""
    boosted = [band for band in BANDS if gains[band] >= 1.0]
    cut = [band for band in BANDS if gains[band] <= -1.0]
    band_ja = {
        "low": "低域",
        "low_mid": "ロー中域",
        "mid": "中域",
        "high_mid": "ハイ中域",
        "high": "高域",
    }
    parts: list[str] = []
    if cut:
        parts.append(("/".join(band_ja[b] for b in cut)) + "を抑える")
    if boosted:
        parts.append(("/".join(band_ja[b] for b in boosted)) + "を出す")
    if not parts:
        parts.append("帯域はフラット")
    stereo = {"narrow": "ステレオ狭め", "moderate": "ステレオ標準", "wide": "ステレオ広げる"}[width_label]
    mono = "・低域はモノ" if low_mono else ""
    return "%s(%s): %s/%s%s" % (label, archetype, "、".join(parts), stereo, mono)


def build_section_spectral_plan(structure: list[str]) -> dict[str, Any]:
    """Return a read-only per-section frequency-band + stereo treatment plan for ``structure``.

    Each section reports its ``archetype``/``energy`` (from the narrative arc), a per-band
    ``gain_db`` EQ move and ``treatment`` (boost/cut/neutral), the resulting ``band_balance``
    (fractions summing to 1.0, comparable to :mod:`targets`), a ``stereo_width`` (0..1, the
    archetype's base width blended with the section energy) with a ``stereo`` label, and a
    ``low_mono`` recommendation. Report-only: it never touches Live.
    """
    if not structure:
        raise ValueError("structure must contain at least one section label")

    arc = build_narrative_arc(list(structure))
    sections: list[dict[str, Any]] = []
    for section in arc["sections"]:
        archetype = section["archetype"]
        energy = float(section["energy"])
        profile = _ARCHETYPE_SPECTRAL.get(archetype, _ARCHETYPE_SPECTRAL["verse"])
        multipliers = profile["bands"]
        gains = {band: _gain_db(multipliers[band]) for band in BANDS}
        treatments = {band: _treatment(gains[band]) for band in BANDS}
        balance = _normalized_balance(gains)
        # Blend the archetype's base width with the section's energy so a bigger moment opens wider.
        width = round(max(0.0, min(1.0, 0.7 * float(profile["width"]) + 0.3 * energy)), 3)
        width_label = _width_label(width)
        low_mono = multipliers["low"] >= _LOW_MONO_THRESHOLD
        sections.append(
            {
                "position": section["position"],
                "label": section["label"],
                "archetype": archetype,
                "energy": energy,
                "gain_db": gains,
                "treatment": treatments,
                "band_balance": balance,
                "stereo_width": width,
                "stereo": width_label,
                "low_mono": low_mono,
                "advice": _advice(section["label"], archetype, gains, width_label, low_mono),
            }
        )

    return {
        "read_only": True,
        "section_count": len(sections),
        "neutral_baseline": dict(_NEUTRAL_BALANCE),
        "bands": list(BANDS),
        "sections": sections,
    }
