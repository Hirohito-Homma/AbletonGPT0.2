"""Plan which tracks play in each song section (arrangement layering / mute plan).

Pure logic, stdlib only -- no Live connection and no NumPy. :func:`build_layering_plan` takes a
song structure (a list of section labels) plus the set's tracks (each with an instrument role) and
works out, section by section, which tracks should be active and which muted, following common
arrangement conventions: a sparse intro, layers added through a build, a full chorus/drop, drums
and bass dropped in a breakdown, and so on. Deterministic and read-only -- it produces the plan;
the server's apply tool sets track mutes to match one chosen section.

:func:`infer_track_role` maps a track name to one of the layering roles
(drums/bass/chords/lead/pad/vocal/fx/perc) by keyword, so the server can build the track list from
`get_state` without the user labelling every track.
"""

from __future__ import annotations

from typing import Any

ROLES = ("drums", "bass", "chords", "lead", "pad", "vocal", "fx", "perc")

# Keyword -> role. Checked in order; the first keyword found in the (lower-cased) name wins.
_ROLE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("kick", "drums"), ("snare", "drums"), ("hat", "drums"), ("drum", "drums"), ("beat", "drums"),
    ("perc", "perc"), ("clap", "perc"), ("shaker", "perc"), ("tom", "perc"), ("conga", "perc"),
    ("sub", "bass"), ("bass", "bass"), ("808", "bass"),
    ("vox", "vocal"), ("vocal", "vocal"), ("voice", "vocal"), ("choir", "vocal"),
    ("lead", "lead"), ("melody", "lead"), ("arp", "lead"), ("pluck", "lead"), ("synth", "lead"),
    ("pad", "pad"), ("string", "pad"), ("atmos", "pad"), ("drone", "pad"),
    ("chord", "chords"), ("key", "chords"), ("piano", "chords"), ("rhodes", "chords"),
    ("organ", "chords"), ("guitar", "chords"), ("stab", "chords"),
    ("fx", "fx"), ("riser", "fx"), ("sweep", "fx"), ("noise", "fx"), ("impact", "fx"),
)

# Section archetype -> the roles that play in it.
_ARCHETYPE_ROLES: dict[str, set[str]] = {
    "intro": {"pad", "chords", "fx"},
    "verse": {"drums", "bass", "chords", "vocal", "perc"},
    "build": {"drums", "bass", "chords", "pad", "fx", "perc"},
    "chorus": {"drums", "bass", "chords", "lead", "pad", "vocal", "fx", "perc"},
    "bridge": {"chords", "pad", "vocal", "lead", "perc"},
    "breakdown": {"pad", "fx", "vocal", "chords"},
    "outro": {"pad", "chords", "fx"},
}

# Label keyword -> archetype. Order matters: more specific keywords come first (e.g. "prechorus"
# and "breakdown" before "chorus"/"bridge") so a substring match picks the right archetype.
_LABEL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("intro", "intro"),
    ("breakdown", "breakdown"),
    ("break", "breakdown"),
    ("prechorus", "build"),
    ("pre-chorus", "build"),
    ("pre", "build"),
    ("build", "build"),
    ("buildup", "build"),
    ("rise", "build"),
    ("chorus", "chorus"),
    ("drop", "chorus"),
    ("hook", "chorus"),
    ("refrain", "chorus"),
    ("bridge", "bridge"),
    ("middle8", "bridge"),
    ("verse", "verse"),
    ("outro", "outro"),
    ("coda", "outro"),
    ("ending", "outro"),
)

# Sections whose label matches nothing get the full arrangement (never silently mutes a track).
_DEFAULT_ARCHETYPE = "chorus"


def infer_track_role(name: str) -> str:
    """Map a track name to a layering role by keyword; unknown names fall back to ``"chords"``."""
    lowered = name.lower()
    for keyword, role in _ROLE_KEYWORDS:
        if keyword in lowered:
            return role
    return "chords"


def section_archetype(label: str) -> str:
    """Map a section label to an arrangement archetype (unknown -> the full-arrangement default)."""
    lowered = label.lower().replace(" ", "").replace("_", "")
    for keyword, archetype in _LABEL_KEYWORDS:
        if keyword in lowered:
            return archetype
    return _DEFAULT_ARCHETYPE


def build_layering_plan(
    structure: list[str],
    tracks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a read-only layering plan: which tracks are active/muted in each section.

    ``structure`` is a list of section labels (e.g. ``["intro", "verse", "chorus"]``). ``tracks``
    is a list of ``{index, name, role}`` (role from :func:`infer_track_role` when the caller does
    not set it). Each section reports the active and muted track names plus a per-track layer list.
    """
    if not structure:
        raise ValueError("structure must contain at least one section label")
    if not tracks:
        raise ValueError("no tracks to lay out")

    resolved_tracks = [
        {
            "index": int(track["index"]),
            "name": str(track.get("name", "")),
            "role": str(track.get("role") or infer_track_role(str(track.get("name", "")))),
        }
        for track in tracks
    ]

    sections: list[dict[str, Any]] = []
    for position, label in enumerate(structure):
        archetype = section_archetype(str(label))
        active_roles = _ARCHETYPE_ROLES[archetype]
        layers = []
        active_names: list[str] = []
        muted_names: list[str] = []
        for track in resolved_tracks:
            is_active = track["role"] in active_roles
            layers.append(
                {
                    "track_index": track["index"],
                    "name": track["name"],
                    "role": track["role"],
                    "active": is_active,
                }
            )
            (active_names if is_active else muted_names).append(track["name"])
        sections.append(
            {
                "position": position,
                "label": str(label),
                "archetype": archetype,
                "active_tracks": active_names,
                "muted_tracks": muted_names,
                "layers": layers,
            }
        )

    return {
        "read_only": True,
        "tracks": resolved_tracks,
        "sections": sections,
    }
