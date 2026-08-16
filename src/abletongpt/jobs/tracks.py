"""Where a plan expects its tracks to land, so it cannot write to someone else's.

A KIHACHI plan addresses tracks by **absolute index**, but `create_track` appends.
Those two only agree when the plan's `first_track_index` equals the number of tracks
the Live Set already had. Nothing enforced that: the plan *declares*
``"modifies_existing_tracks": false`` in its safety block, and with a stale offset the
declaration is simply false — `apply_live_drum_kit` would load a kit onto an existing
empty track, and clips would be written into existing tracks' empty slots. Offline
preflight cannot catch it, because it never sees the Set.

This module computes what the plan expects (pure, no Live) and offers one check
against a live Set (one read-only `get_state`, before any mutation).

Pure and stdlib-only apart from the injected bridge.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: Commands whose ``track_index`` addresses a track the plan expects to own.
TRACK_TARGETING_COMMANDS = frozenset(
    {
        "apply_live_instrument_selection",
        "apply_live_drum_kit",
        "create_midi_clip",
        "set_clip_send_envelope",
        "set_clip_parameter_envelope",
        "copy_session_clip_to_arrangement",
    }
)

#: Commands that append a track. ``import_vocal_take`` does not say so in its
#: name: it creates the audio track it imports onto. Counting it matters on
#: resume, where the expected track count is the base index plus the creations
#: already done -- miss it and a resumed plan reads the Set as one track ahead
#: of itself and refuses to continue.
TRACK_CREATING_COMMANDS = frozenset({"create_track", "import_vocal_take"})


class TrackBaselineMismatch(RuntimeError):
    """The Live Set does not have the track count this plan was written against."""


@dataclass(frozen=True)
class TrackExpectation:
    """What a plan assumes about the Set it is about to be applied to."""

    #: Lowest track index the plan writes to — the plan's ``first_track_index``.
    base_index: int
    #: How many tracks the plan creates.
    creates: int
    #: How many of those creations already ran (non-zero only on resume).
    creates_done: int

    @property
    def expected_track_count(self) -> int:
        """Tracks the Set must already have for the next step to land correctly.

        Fresh run: the base index itself, because the first appended track has to
        become index ``base_index``. Resume: that plus the tracks already created.
        """
        return self.base_index + self.creates_done


def _appends(step: Any) -> bool:
    """Whether a ``create_track`` step appends rather than inserting at an index."""
    index = step.params.get("index", -1)
    return isinstance(index, int) and not isinstance(index, bool) and index == -1


def build_track_expectation(
    plan: Any, completed_step_ids: Iterable[str] = ()
) -> TrackExpectation | None:
    """What ``plan`` expects of the Set, or ``None`` when nothing can be checked.

    ``None`` means "no opinion", never "safe": it is returned when the plan targets
    no tracks at all, or when a `create_track` step inserts at an explicit index
    instead of appending. An explicit index makes the landing position depend on the
    insert order rather than on the track count, so the simple arithmetic here would
    be wrong — and a wrong guard is worse than none. KIHACHI always appends
    (``index: -1``), so its plans are always checkable.
    """
    done = set(completed_step_ids)
    targeted: list[int] = []
    creates = 0
    creates_done = 0
    for step in plan.steps:
        if step.command in TRACK_CREATING_COMMANDS:
            if not _appends(step):
                return None
            creates += 1
            if step.step_id in done:
                creates_done += 1
            continue
        if step.command not in TRACK_TARGETING_COMMANDS:
            continue
        index = step.params.get("track_index")
        if isinstance(index, int) and not isinstance(index, bool):
            targeted.append(index)

    if not targeted:
        return None
    return TrackExpectation(min(targeted), creates, creates_done)


def verify_track_baseline(bridge: Any, expectation: TrackExpectation) -> int:
    """Refuse to start unless Live has exactly the tracks the plan assumes.

    Read-only, and called before the first mutating step, so a mismatch costs
    nothing. Returns the observed track count.
    """
    state = bridge.call("get_state")
    tracks = state.get("tracks") if isinstance(state, Mapping) else None
    if not isinstance(tracks, list):
        raise TrackBaselineMismatch("get_state did not report a track list")
    actual = len(tracks)
    expected = expectation.expected_track_count
    if actual == expected:
        return actual

    if expectation.creates_done:
        detail = (
            "resuming this plan expects %d track(s): its first track index %d plus "
            "the %d it already created" % (expected, expectation.base_index, expectation.creates_done)
        )
        fix = (
            "the Set changed since the run halted; re-import the plan against the "
            "current Set rather than resuming into moved indices"
        )
    else:
        detail = (
            "this plan was written for a Set with %d track(s) (its first track "
            "index)" % expected
        )
        fix = "rebuild the plan with --first-track-index %d" % actual
    raise TrackBaselineMismatch(
        "refusing to run: Live has %d track(s) but %s. Applying it would write to "
        "tracks the plan does not own. Fix: %s." % (actual, detail, fix)
    )
