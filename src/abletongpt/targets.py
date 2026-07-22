"""Built-in genre mix/master targets to compare a mix against without a reference track.

Pure logic, stdlib only -- no Live connection and no NumPy. Each target is a flat audio
*profile* in the exact shape :func:`abletongpt.reference.build_reference_comparison` consumes,
so a target can be dropped in wherever a real reference profile would go. The server tool builds
the *mix* profile from :mod:`abletongpt.loudness`/:mod:`abletongpt.audio` and compares it against
one of these presets, giving loudness + band-balance guidance for people who do not have a
reference song on hand.

These numbers are **curated approximations**, not measured from any specific master: streaming
loudness norms plus typical genre mastering practice for LUFS/LRA/true-peak/crest, and plausible
level-independent five-band energy shares (low 20-120 Hz, low_mid 120-500, mid 500-2000,
high_mid 2000-6000, high 6000-20000; summing to 1.0). Treat the output as directional guidance
("your mix has less low energy than a typical EDM master"), not lab-grade truth. Tone (spectral
centroid) and stereo image are intentionally left unset -- they vary too much per record to pin a
defensible per-genre number -- so the comparison scores loudness, dynamics, and band balance only.
"""

from __future__ import annotations

from typing import Any

# Each entry: a short human description plus a partial reference profile. Fields left out
# (centroid_hz, rolloff_hz, width_side_ratio, correlation) are None so the comparator skips
# those dimensions instead of scoring against a fabricated number. Band fractions sum to 1.0.
GENRE_TARGETS: dict[str, dict[str, Any]] = {
    "streaming": {
        "description": "Platform loudness normalization (Spotify/Apple/YouTube ~ -14 LUFS).",
        "integrated_lufs": -14.0,
        "loudness_range_lu": 8.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 12.0,
        "bands": {"low": 0.28, "low_mid": 0.30, "mid": 0.26, "high_mid": 0.11, "high": 0.05},
    },
    "modern-pop": {
        "description": "Loud, polished pop master; bass-forward but balanced.",
        "integrated_lufs": -9.5,
        "loudness_range_lu": 6.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 10.0,
        "bands": {"low": 0.30, "low_mid": 0.29, "mid": 0.25, "high_mid": 0.11, "high": 0.05},
    },
    "edm": {
        "description": "Club/festival electronic; very loud and compressed, strong lows.",
        "integrated_lufs": -7.5,
        "loudness_range_lu": 5.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 8.0,
        "bands": {"low": 0.34, "low_mid": 0.28, "mid": 0.22, "high_mid": 0.11, "high": 0.05},
    },
    "hip-hop": {
        "description": "Modern hip-hop/trap; heavy sub and low end, loud.",
        "integrated_lufs": -8.5,
        "loudness_range_lu": 6.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 9.0,
        "bands": {"low": 0.36, "low_mid": 0.28, "mid": 0.21, "high_mid": 0.10, "high": 0.05},
    },
    "rock": {
        "description": "Rock/indie band master; mid-forward with more dynamics.",
        "integrated_lufs": -9.5,
        "loudness_range_lu": 8.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 11.0,
        "bands": {"low": 0.26, "low_mid": 0.28, "mid": 0.28, "high_mid": 0.12, "high": 0.06},
    },
    "acoustic": {
        "description": "Acoustic/singer-songwriter; natural, open dynamics.",
        "integrated_lufs": -13.0,
        "loudness_range_lu": 10.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 13.0,
        "bands": {"low": 0.24, "low_mid": 0.29, "mid": 0.28, "high_mid": 0.13, "high": 0.06},
    },
    "jazz": {
        "description": "Jazz; warm, wide dynamic range, light limiting.",
        "integrated_lufs": -16.0,
        "loudness_range_lu": 12.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 15.0,
        "bands": {"low": 0.25, "low_mid": 0.30, "mid": 0.28, "high_mid": 0.12, "high": 0.05},
    },
    "classical": {
        "description": "Classical/orchestral; very wide dynamics, minimal processing.",
        "integrated_lufs": -18.0,
        "loudness_range_lu": 15.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 18.0,
        "bands": {"low": 0.23, "low_mid": 0.30, "mid": 0.29, "high_mid": 0.13, "high": 0.05},
    },
    "podcast": {
        "description": "Spoken-word/podcast; mid-forward, controlled dynamics (~ -16 LUFS).",
        "integrated_lufs": -16.0,
        "loudness_range_lu": 5.0,
        "true_peak_dbtp": -1.0,
        "crest_factor_db": 11.0,
        "bands": {"low": 0.14, "low_mid": 0.30, "mid": 0.36, "high_mid": 0.15, "high": 0.05},
    },
}


def list_targets() -> list[dict[str, Any]]:
    """Return the available built-in targets as ``{name, description, integrated_lufs}`` rows."""
    return [
        {
            "name": name,
            "description": target["description"],
            "integrated_lufs": target["integrated_lufs"],
        }
        for name, target in GENRE_TARGETS.items()
    ]


def get_target(name: str) -> dict[str, Any]:
    """Return a copy of a built-in target profile by name.

    The name is matched case-insensitively and treats ``_`` and ``-`` as the same, so
    ``"Modern Pop"`` and ``"modern_pop"`` both resolve to ``"modern-pop"``. Raises
    :class:`KeyError` (message lists the valid names) when there is no match.
    """
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    target = GENRE_TARGETS.get(normalized)
    if target is None:
        available = ", ".join(sorted(GENRE_TARGETS))
        raise KeyError("unknown target %r; available targets: %s" % (name, available))
    profile = {"target": normalized, "description": target["description"]}
    for key, value in target.items():
        if key == "description":
            continue
        profile[key] = dict(value) if isinstance(value, dict) else value
    return profile
