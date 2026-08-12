"""Read the *meaning* of a song's development and turn it into per-section change directives.

Pure logic, stdlib only -- no Live connection and no NumPy. Where :mod:`layering` decides *which*
tracks play in each section, this module decides *how much energy* each section should carry and
*what kind of change* it deserves, so the same material can be developed with intent rather than
repeated verbatim. :func:`build_narrative_arc` reads a song structure (a list of section labels),
assigns each section an energy value (0..1) shaped by common arrangement conventions -- a sparse
intro, a build that ramps into the chorus, a breakdown that drops before a harder final chorus, a
recurring section that grows each time it returns -- and derives, for every section, its tension
(rising/falling/hold), a narrative role (setup/development/climax/release/resolution/reset), and a
set of concrete *development directives* (density, dynamics, register, motion into the next
section, and whether to vary a returning section).

Deterministic and read-only: it produces the arc and the directives; a separate create/apply tool
consumes them (e.g. to tile, vary, or layer the material section by section). Reuses
:func:`layering.section_archetype` so the two modules always agree on how a label maps to an
arrangement archetype.
"""

from __future__ import annotations

from typing import Any

from .layering import section_archetype

# Base energy per arrangement archetype (0..1), before any context adjustment.
_ARCHETYPE_ENERGY: dict[str, float] = {
    "intro": 0.25,
    "verse": 0.45,
    "build": 0.70,
    "chorus": 0.90,
    "bridge": 0.55,
    "breakdown": 0.20,
    "outro": 0.30,
}

# How much a repeated archetype grows each time it returns (the 2nd chorus is bigger than the 1st).
_RECURRENCE_STEP = 0.06
_RECURRENCE_CAP = 0.12

# A section counts as a meaningful rise/fall only past this delta; smaller moves read as "hold".
_TENSION_EPS = 0.08

# Energy -> density bucket thresholds (upper bound of each bucket).
_DENSITY_BUCKETS: tuple[tuple[float, str], ...] = (
    (0.30, "sparse"),
    (0.55, "light"),
    (0.78, "medium"),
    (0.92, "dense"),
    (1.01, "full"),
)


def _density_for(energy: float) -> str:
    for upper, label in _DENSITY_BUCKETS:
        if energy < upper:
            return label
    return "full"


def _velocity_target(energy: float) -> int:
    """Map energy to a rough target velocity (1..127) for the section's loudest voices."""
    return max(1, min(127, int(round(45 + energy * 82))))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _base_energies(archetypes: list[str]) -> list[float]:
    """Base archetype energy plus a per-archetype recurrence bump (returning sections grow)."""
    seen: dict[str, int] = {}
    energies: list[float] = []
    for archetype in archetypes:
        occurrence = seen.get(archetype, 0)
        bump = min(_RECURRENCE_CAP, _RECURRENCE_STEP * occurrence)
        energies.append(_clamp01(_ARCHETYPE_ENERGY.get(archetype, 0.5) + bump))
        seen[archetype] = occurrence + 1
    return energies


def _shape_energies(archetypes: list[str], energies: list[float]) -> list[float]:
    """Second pass: ramp builds toward the next section, boost a peak that follows a low, lift the
    final chorus. Neighbour-aware, so it captures the *meaning* of the sequence, not just labels."""
    count = len(energies)
    shaped = list(energies)
    last_chorus = max(
        (index for index, archetype in enumerate(archetypes) if archetype == "chorus"),
        default=-1,
    )
    for index, archetype in enumerate(archetypes):
        prev_energy = shaped[index - 1] if index > 0 else None
        next_energy = energies[index + 1] if index + 1 < count else None
        value = shaped[index]
        if archetype == "build" and next_energy is not None:
            # A build should climb from where we are toward the section it sets up.
            floor = prev_energy if prev_energy is not None else value
            value = max(value, 0.35 * floor + 0.65 * next_energy)
        if archetype == "chorus" and prev_energy is not None and prev_energy < 0.35:
            # A chorus that lands straight after a breakdown hits harder by contrast.
            value += 0.05
        if archetype == "chorus" and index == last_chorus and last_chorus != -1:
            # The last chorus is the emotional peak of the arrangement.
            value += 0.05
        shaped[index] = _clamp01(value)
    return shaped


def _tension(delta: float, is_first: bool) -> str:
    if is_first:
        return "open"
    if delta > _TENSION_EPS:
        return "rise"
    if delta < -_TENSION_EPS:
        return "fall"
    return "hold"


def _role(
    archetype: str,
    energy: float,
    prev_energy: float | None,
    next_energy: float | None,
    is_last: bool,
) -> str:
    """A narrative role for the section from its archetype and its place in the energy curve."""
    if archetype == "intro" or prev_energy is None:
        return "setup"
    if archetype == "breakdown":
        return "reset"
    is_local_peak = (prev_energy is None or energy >= prev_energy) and (
        next_energy is None or energy >= next_energy
    )
    if is_local_peak and energy >= 0.8:
        return "climax"
    if next_energy is not None and next_energy > energy + _TENSION_EPS:
        return "development"
    if prev_energy is not None and energy < prev_energy - _TENSION_EPS:
        return "release"
    if is_last:
        return "resolution"
    return "development"


def _motion(archetype: str, next_archetype: str | None, is_last: bool) -> str:
    """A transition directive for how this section should hand off to the next one."""
    if is_last or next_archetype is None:
        return "resolve/tail"
    if archetype == "build":
        return "riser+fill into next"
    if next_archetype == "chorus" and archetype != "chorus":
        return "fill+impact into chorus"
    if archetype == "chorus" and next_archetype in ("breakdown", "verse"):
        return "drop out into next"
    if next_archetype == "breakdown":
        return "strip back"
    return "carry through"


def _register(archetype: str, role: str) -> str:
    if role == "climax" or archetype == "chorus":
        return "lift lead +12 (octave up), full range"
    if archetype == "breakdown":
        return "low/mid only, thin the top"
    if archetype == "build":
        return "climb register toward the drop"
    if archetype in ("intro", "outro"):
        return "mid, filtered"
    return "mid"


def _dynamics(archetype: str, tension: str, energy: float) -> str:
    if archetype == "build" or tension == "rise":
        return "crescendo"
    if archetype == "breakdown" or tension == "fall":
        return "pull back"
    if energy >= 0.88:
        return "push/peak"
    return "steady"


def _advice(
    label: str, archetype: str, role: str, density: str, tension: str, vary: bool
) -> str:
    """A short Japanese one-liner summarising the intended change for the section."""
    role_ja = {
        "setup": "提示",
        "development": "展開",
        "climax": "クライマックス",
        "release": "開放",
        "resolution": "収束",
        "reset": "リセット",
    }.get(role, role)
    tension_ja = {"open": "開始", "rise": "上昇", "fall": "下降", "hold": "維持"}.get(tension, tension)
    density_ja = {
        "sparse": "薄く",
        "light": "軽め",
        "medium": "標準",
        "dense": "厚く",
        "full": "フル",
    }.get(density, density)
    vary_ja = "・前回から変化を付ける" if vary else ""
    return "%s(%s): %s/密度%s/テンション%s%s" % (label, archetype, role_ja, density_ja, tension_ja, vary_ja)


def _shape(peak_position: int, count: int) -> str:
    if count <= 2:
        return "short"
    third = count / 3.0
    if peak_position <= third:
        return "front-loaded"
    if peak_position >= 2 * third:
        return "climactic"
    return "arch"


def build_narrative_arc(structure: list[str]) -> dict[str, Any]:
    """Return a read-only narrative arc for ``structure`` (a list of section labels).

    Each section reports its ``archetype`` (via :func:`layering.section_archetype`), an ``energy``
    value (0..1) shaped by recurrence, build ramps, post-breakdown contrast and a final-chorus lift,
    its ``tension`` relative to the previous section, a narrative ``role``, and a set of
    ``directives`` (density/dynamics/register/motion/vary + a target velocity) describing the change
    the section should carry. The top level reports the energy curve, the peak position and the
    overall shape. Deterministic; never touches Live.
    """
    if not structure:
        raise ValueError("structure must contain at least one section label")

    labels = [str(label) for label in structure]
    archetypes = [section_archetype(label) for label in labels]
    energies = _shape_energies(archetypes, _base_energies(archetypes))
    count = len(labels)
    peak_position = max(range(count), key=lambda index: energies[index])

    # Count occurrences so a returning section can be marked for variation.
    seen: dict[str, int] = {}
    sections: list[dict[str, Any]] = []
    for index in range(count):
        archetype = archetypes[index]
        energy = round(energies[index], 4)
        prev_energy = energies[index - 1] if index > 0 else None
        next_energy = energies[index + 1] if index + 1 < count else None
        next_archetype = archetypes[index + 1] if index + 1 < count else None
        is_last = index == count - 1
        delta = round(energy - prev_energy, 4) if prev_energy is not None else 0.0
        tension = _tension(delta, prev_energy is None)
        role = _role(archetype, energy, prev_energy, next_energy, is_last)
        density = _density_for(energy)
        occurrence = seen.get(archetype, 0)
        seen[archetype] = occurrence + 1
        # A returning musical section (verse/chorus/bridge) should be varied, not photocopied.
        vary = occurrence > 0 and archetype in ("verse", "chorus", "bridge")
        directives = {
            "density": density,
            "dynamics": _dynamics(archetype, tension, energy),
            "register": _register(archetype, role),
            "motion": _motion(archetype, next_archetype, is_last),
            "target_velocity": _velocity_target(energy),
            "vary": vary,
        }
        sections.append(
            {
                "position": index,
                "label": labels[index],
                "archetype": archetype,
                "energy": energy,
                "tension": tension,
                "tension_delta": delta,
                "role": role,
                "directives": directives,
                "advice": _advice(labels[index], archetype, role, density, tension, vary),
            }
        )

    return {
        "read_only": True,
        "section_count": count,
        "peak_position": peak_position,
        "peak_label": labels[peak_position],
        "shape": _shape(peak_position, count),
        "energy_curve": [round(value, 4) for value in energies],
        "sections": sections,
    }
