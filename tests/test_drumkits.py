from __future__ import annotations

import pytest

from abletongpt.drumkits import (
    ALL_KIT_NAMES,
    SUPPORTED_KIT_ROLES,
    build_drum_kit_selection,
)
from abletongpt.composition import GENRE_PROFILES
from abletongpt.instruments import INSTRUMENTS


def test_selection_is_deterministic():
    first = build_drum_kit_selection("edm", "dark")
    second = build_drum_kit_selection("edm", "dark")

    assert first == second


def test_the_manually_verified_kit_leads_the_kihachi_case():
    # KIHACHI's dub/tech-house SongSpec collapses to edm + dark, and 909 Core Kit
    # is the kit whose sound was confirmed by hand before any of this was wired.
    selection = build_drum_kit_selection("edm", "dark")

    assert selection["selected_kit"] == "909 Core Kit"
    assert selection["candidates"][0] == "909 Core Kit"


def test_percussion_asks_for_percussion_not_a_drum_machine():
    selection = build_drum_kit_selection("edm", "dark", "percussion")

    assert selection["selected_kit"] == "Percussion Core Kit"
    # The genre kits stay on as fallback rather than being replaced.
    assert "909 Core Kit" in selection["candidates"]


def test_kick_and_snare_take_the_same_kit_as_the_whole_part():
    whole = build_drum_kit_selection("edm", "dark", "drums")

    for role in ("kick", "snare"):
        assert build_drum_kit_selection("edm", "dark", role)["candidates"] == whole["candidates"]


def test_mood_reranks_within_the_genre_and_never_outside_it():
    genre_pool = set(build_drum_kit_selection("jazz", "chill")["candidates"])

    for mood in ("bright", "uplifting", "chill", "dark", "bittersweet", "tense"):
        assert set(build_drum_kit_selection("jazz", mood)["candidates"]) == genre_pool


def test_mood_can_change_the_leading_kit_but_only_within_the_genre():
    # A nudge, not an override: mood re-ranks the genre's own kits and cannot
    # promote one the genre never listed. It only overturns the genre's first
    # choice when a mood-preferred kit was already close behind it, which is why
    # this is asserted on a genre where that happens rather than on all of them.
    chill = build_drum_kit_selection("hiphop", "chill")
    dark = build_drum_kit_selection("hiphop", "dark")

    assert chill["selected_kit"] == "Boom Bap Kit"
    assert dark["selected_kit"] == "808 Core Kit"
    assert set(chill["candidates"]) == set(dark["candidates"])


def test_preferred_kit_leads_but_keeps_the_derived_fallbacks():
    selection = build_drum_kit_selection("edm", "dark", "drums", "My Own Kit")

    assert selection["candidates"][0] == "My Own Kit"
    assert "909 Core Kit" in selection["candidates"]
    # An unknown name is allowed here on purpose: a user's own kit is a
    # legitimate browser item, and the browser walk is what rejects a typo.
    assert "My Own Kit" not in ALL_KIT_NAMES


def test_preferred_kit_is_not_duplicated_when_it_is_already_a_candidate():
    selection = build_drum_kit_selection("edm", "dark", "drums", "808 Core Kit")

    assert selection["candidates"].count("808 Core Kit") == 1
    assert selection["candidates"][0] == "808 Core Kit"


def test_every_genre_and_role_yields_candidates():
    for genre in GENRE_PROFILES:
        for role in sorted(SUPPORTED_KIT_ROLES):
            selection = build_drum_kit_selection(genre, "dark", role)
            assert selection["genre"] == genre
            assert selection["candidates"]
            assert len(selection["candidates"]) == len(set(selection["candidates"]))


def test_no_candidate_is_a_content_free_device():
    # The bug this module exists to fix: Drum Rack and Impulse insert cleanly and
    # stay silent. A kit candidate must never be one of them.
    silent = {name for name, profile in INSTRUMENTS.items() if profile["requires_content"]}

    assert silent
    assert not (ALL_KIT_NAMES & silent)


def test_selection_never_carries_a_browser_path_or_uri():
    selection = build_drum_kit_selection("edm", "dark")

    assert "path" not in selection
    assert "uri" not in selection
    assert selection["browser_category"] == "drums"


@pytest.mark.parametrize(
    "genre,mood,role",
    [("polka", "dark", "drums"), ("edm", "smug", "drums"), ("edm", "dark", "bass")],
)
def test_unsupported_inputs_are_refused(genre, mood, role):
    with pytest.raises(ValueError):
        build_drum_kit_selection(genre, mood, role)
