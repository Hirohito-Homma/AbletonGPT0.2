"""Role/genre/mood -> ordered Live *drum kit* candidates.

The sibling of :mod:`instruments`, and deliberately separate from it. A native
synth is a *device* that makes sound the moment it is inserted, so
``insert_first_available_instrument`` finishes the job. A Drum Rack does not:
inserting the empty device produces a silent sampler, which is exactly why
``instruments.py`` marks ``Drum Rack``/``Impulse`` as ``requires_content`` and
why the KIHACHI contract kept drums out of instrument selection entirely.

A kit is therefore not a device name but a *Browser preset* -- a ``.adg`` rack
that has to be found in Live's browser and loaded. This module owns the musical
half of that (which kit names, in which order); it does **not** own where they
live in the browser tree. Nothing here knows a path or a URI, because the
browser layout is a fact about the running Live installation and is resolved by
walking it, not by guessing (see ``jobs.executors._apply_live_drum_kit``).

Every name below is from Live's **Core Library**, which ships with Intro,
Standard and Suite alike, so a candidate list cannot be emptied by edition. The
lists are still ordered fallbacks rather than promises: a user can move or
remove Core Library content, so resolution always verifies against the browser
before loading and the caller falls through to the next candidate.

Pure and stdlib-only. Deterministic: the same role/genre/mood always yields the
same ordered list.
"""

from __future__ import annotations

from typing import Any

from .composition import GENRE_PROFILES, MOOD_PROGRESSIONS

#: Kit roles this module can select for. ``drums`` is the whole kit on one
#: track; the other three are the split layout KIHACHI emits when one GM drum
#: part is spread over three Live tracks. Each split track still needs its own
#: kit, because a Live track with no instrument is silent regardless of how few
#: pitches its clip uses.
SUPPORTED_KIT_ROLES = {"drums", "kick", "snare", "percussion"}

#: Genre -> ordered Core Library kit names.
_GENRE_KITS: dict[str, list[str]] = {
    "edm": ["909 Core Kit", "808 Core Kit", "AG Techno Kit", "707 Core Kit", "Chicago Kit"],
    "tech_house": ["909 Core Kit", "AG Techno Kit", "Chicago Kit", "707 Core Kit", "808 Core Kit"],
    "dub_techno": ["909 Core Kit", "AG Techno Kit", "707 Core Kit", "606 Core Kit", "Chicago Kit"],
    "deep_house": ["909 Core Kit", "Chicago Kit", "707 Core Kit", "808 Core Kit", "LD Core Kit"],
    "minimal_techno": ["909 Core Kit", "AG Techno Kit", "707 Core Kit", "606 Core Kit", "Chicago Kit"],
    "dub": ["606 Core Kit", "808 Core Kit", "909 Core Kit", "LD Core Kit", "Boom Bap Kit"],
    "funk": ["Gen Purpose Kit", "Dry Session Kit", "707 Core Kit", "909 Core Kit", "Acuff Kit"],
    "hiphop": ["808 Core Kit", "Boom Bap Kit", "DMX Core Kit", "LD Core Kit", "909 Core Kit"],
    "rnb": ["808 Core Kit", "DMX Core Kit", "LD Core Kit", "Boom Bap Kit", "909 Core Kit"],
    "jazz": ["Dry Session Kit", "Gen Purpose Kit", "Acuff Kit", "Plymouth Kit", "Boom Bap Kit"],
    "rock": ["Acuff Kit", "Plymouth Kit", "Gen Purpose Kit", "Dry Session Kit", "Glide Kit"],
    "lofi": ["Boom Bap Kit", "DMX Core Kit", "606 Core Kit", "LD Core Kit", "Dry Session Kit"],
    "pop": ["909 Core Kit", "808 Core Kit", "Gen Purpose Kit", "707 Core Kit", "Dry Session Kit"],
}

#: Mood nudges the genre order without introducing a kit the genre never had.
#: A mood cannot override the genre, it can only re-rank inside it -- the same
#: rule ``instruments.py`` follows.
_MOOD_PREFERENCES: dict[str, list[str]] = {
    "bright": ["707 Core Kit", "606 Core Kit", "Gen Purpose Kit", "Chicago Kit"],
    "uplifting": ["707 Core Kit", "909 Core Kit", "Gen Purpose Kit", "Chicago Kit"],
    "chill": ["Boom Bap Kit", "Dry Session Kit", "LD Core Kit", "606 Core Kit"],
    "dark": ["909 Core Kit", "808 Core Kit", "AG Techno Kit", "DMX Core Kit"],
    "bittersweet": ["Dry Session Kit", "LD Core Kit", "Boom Bap Kit", "Plymouth Kit"],
    "tense": ["AG Techno Kit", "909 Core Kit", "Chicago Kit", "808 Core Kit"],
}

#: Percussion is the one split role with its own material. Kick and snare come
#: from the same kit the whole part would have used, because they are that
#: kit's kick and snare; percussion is hats, toms and cymbals, which a dedicated
#: percussion kit voices better than a drum machine does.
_PERCUSSION_KITS = ["Percussion Core Kit", "Perc Kitchen Kit", "Perc Tamuz Kit"]

#: Every kit name this module can ever propose. Used by the offline KIHACHI
#: preflight to stand in for a browser it has no connection to, so an import can
#: be fully validated before Live is even running.
ALL_KIT_NAMES = frozenset(
    name
    for names in list(_GENRE_KITS.values()) + [_PERCUSSION_KITS]
    for name in names
)

_ROLE_NAMES_JA = {
    "drums": "ドラム",
    "kick": "キック",
    "snare": "スネア",
    "percussion": "パーカッション",
}

#: How many candidates a selection carries. Enough to survive missing Core
#: Library content, short enough that resolution stays one browser walk.
_MAX_CANDIDATES = 5


def build_drum_kit_selection(
    genre: str,
    mood: str,
    role: str = "drums",
    preferred_kit: str = "",
) -> dict[str, Any]:
    """Ordered Core Library kit candidates for one drum track.

    ``preferred_kit`` puts a caller-named kit first and keeps the derived order
    behind it as fallback. It is *not* validated against a list of known names:
    unlike a native device there is no allowlist to check against, since a user's
    own kit is an equally legitimate browser item. It is still resolved against
    the live browser before anything loads, so an unknown name fails by finding
    nothing rather than by loading something unintended.
    """

    if genre not in GENRE_PROFILES:
        raise ValueError("unsupported genre")
    if mood not in MOOD_PROGRESSIONS:
        raise ValueError("unsupported mood")
    if role not in SUPPORTED_KIT_ROLES:
        raise ValueError(
            "unsupported drum kit role: %r (expected %s)"
            % (role, ", ".join(sorted(SUPPORTED_KIT_ROLES)))
        )
    if not isinstance(preferred_kit, str):
        raise ValueError("preferred_kit must be a string")

    base = list(_GENRE_KITS[genre])
    scores = {name: 100.0 - position * 10.0 for position, name in enumerate(base)}
    for position, name in enumerate(_MOOD_PREFERENCES[mood]):
        if name in scores:
            scores[name] += 12.0 - position * 2.0
    ordered = sorted(base, key=lambda name: (-scores[name], base.index(name)))

    if role == "percussion":
        ordered = _PERCUSSION_KITS + [
            name for name in ordered if name not in _PERCUSSION_KITS
        ]

    preferred = preferred_kit.strip()
    if preferred:
        ordered = [preferred] + [name for name in ordered if name != preferred]

    candidates = ordered[:_MAX_CANDIDATES]
    role_name = _ROLE_NAMES_JA[role]
    if preferred:
        reason = (
            "ユーザー指定の%sを第一候補にし、見つからない場合は%sの%s向け候補へフォールバックします。"
            % (preferred, genre, role_name)
        )
    elif role == "percussion":
        reason = (
            "%sのパーカッションはキットのキック／スネアではなく打楽器音を必要とするため、"
            "専用のパーカッションキットを優先します。" % genre
        )
    else:
        reason = (
            "%sの%sに対して、%sのリズム語法と%sの質感を両立しやすい%sを選択しました。"
            % (genre, role_name, genre, mood, candidates[0])
        )

    return {
        "role": role,
        "role_name_ja": role_name,
        "genre": genre,
        "mood": mood,
        "selected_kit": candidates[0],
        "candidates": candidates,
        "reason": reason,
        "browser_category": "drums",
        "resolution": (
            "候補名はLiveブラウザを実際に走査して照合します。パスやURIはKIHACHIにもこのモジュールにも"
            "存在せず、実行時のLiveインストールから解決します。"
        ),
        "apply_contract": {
            "tool": "apply_live_drum_kit",
            "requires_confirmation": True,
            "one_track_per_call": True,
            "one_kit_per_track": True,
            "deletes_or_replaces_existing_instrument": False,
        },
    }
