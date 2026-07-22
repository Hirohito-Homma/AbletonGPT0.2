"""Ready-made :class:`ArrangementPlan` factories shared across the CLI.

The default is a compact dark-tech-house layout: a contiguous intro -> outro song
structure whose ``section_id``/``source_scene`` use the same lowercase vocabulary the
Arrange Engine emits, so :func:`~abletongpt.jobs.build_job_plan` maps it cleanly. Bars
are 1-based and positive so the result passes ``cli.arrange validate`` as-is.

Both ``cli.arrange create-simple`` and ``cli.jobs arrange-run`` build their default
arrangement from here, so the two entry points can never drift apart.
"""

from __future__ import annotations

from typing import Callable

from .models import ArrangementPlan, ArrangementSection

#: Name used when a caller does not supply one (e.g. ``arrange-run`` with no ``--name``).
DEFAULT_ARRANGEMENT_NAME = "dark_tech_house"

#: Style selected when a caller does not pass ``--style``.
DEFAULT_STYLE = "dark-tech-house"

# A section spec row: (section_id, display_name, source_scene, relative_length_bars,
# transition). Start bars are derived (contiguous, 1-based) rather than stored, so any
# layout can be rescaled to a different total length while staying gap-free.
_SectionSpec = tuple[str, str, str, int, str]

#: dark-tech-house layout. Relative lengths sum to 56 (the built-in default length).
_SIMPLE_SECTIONS: tuple[_SectionSpec, ...] = (
    ("intro", "Intro", "intro", 8, "none"),
    ("groove", "Groove", "groove", 16, "fill"),
    ("break", "Break", "break", 8, "break"),
    ("drop", "Drop", "drop", 16, "fill"),
    ("outro", "Outro", "outro", 8, "none"),
)

#: deep-house layout: smoother and warmer than dark-tech-house, with a chord intro and a
#: mid-track breakdown between two main grooves. Relative lengths sum to 64.
_DEEP_HOUSE_SECTIONS: tuple[_SectionSpec, ...] = (
    ("intro", "Intro", "intro", 8, "none"),
    ("groove_a", "Groove A", "groove_a", 8, "fill"),
    ("chord_intro", "Chord Intro", "chord_intro", 8, "none"),
    ("main_groove", "Main Groove", "main_groove", 16, "fill"),
    ("breakdown", "Breakdown", "breakdown", 8, "break"),
    ("main_groove_2", "Main Groove 2", "main_groove_2", 8, "fill"),
    ("outro", "Outro", "outro", 8, "none"),
)

#: deep-house defaults, applied when the caller leaves tempo/length unset.
DEEP_HOUSE_DEFAULT_NAME = "deep_house"
DEEP_HOUSE_DEFAULT_TEMPO = 122.0
DEEP_HOUSE_DEFAULT_BARS = 64

#: minimal-techno layout: more mechanical and repetitive than deep-house, and more pared
#: back than dark-tech-house -- a hypnotic build of pulse/hat/bass layers around a single
#: breakdown and drive. Relative lengths sum to 64.
_MINIMAL_TECHNO_SECTIONS: tuple[_SectionSpec, ...] = (
    ("intro", "Intro", "intro", 8, "none"),
    ("pulse_groove", "Pulse Groove", "pulse_groove", 8, "fill"),
    ("hat_motion", "Hat Motion", "hat_motion", 8, "none"),
    ("bass_lock", "Bass Lock", "bass_lock", 16, "fill"),
    ("breakdown", "Breakdown", "breakdown", 8, "break"),
    ("main_drive", "Main Drive", "main_drive", 8, "fill"),
    ("outro", "Outro", "outro", 8, "none"),
)

#: minimal-techno defaults, applied when the caller leaves tempo/length unset.
MINIMAL_TECHNO_DEFAULT_NAME = "minimal_techno"
MINIMAL_TECHNO_DEFAULT_TEMPO = 126.0
MINIMAL_TECHNO_DEFAULT_BARS = 64

#: dub-techno layout: deep and spacey -- echoing chords, a sub-heavy groove, and delay
#: swells around a dubbed-out break. More floating than minimal-techno, harder than
#: deep-house. Relative lengths sum to 64.
_DUB_TECHNO_SECTIONS: tuple[_SectionSpec, ...] = (
    ("intro", "Intro", "intro", 8, "none"),
    ("chord_echo", "Chord Echo", "chord_echo", 8, "none"),
    ("sub_groove", "Sub Groove", "sub_groove", 8, "fill"),
    ("delay_rise", "Delay Rise", "delay_rise", 16, "fill"),
    ("dub_break", "Dub Break", "dub_break", 8, "break"),
    ("main_echo", "Main Echo", "main_echo", 8, "fill"),
    ("outro", "Outro", "outro", 8, "none"),
)

#: dub-techno defaults, applied when the caller leaves tempo/length unset.
DUB_TECHNO_DEFAULT_NAME = "dub_techno"
DUB_TECHNO_DEFAULT_TEMPO = 124.0
DUB_TECHNO_DEFAULT_BARS = 64


def _scaled_lengths(base_lengths: list[int], total_bars: int) -> list[int]:
    """Scale ``base_lengths`` so they sum to exactly ``total_bars``.

    Every section keeps its relative weight (rounded, at least 1 bar); the final section
    absorbs the rounding remainder so the total lands on ``total_bars`` precisely.
    """
    base_total = sum(base_lengths)
    scaled = [max(1, round(length * total_bars / base_total)) for length in base_lengths[:-1]]
    scaled.append(max(1, total_bars - sum(scaled)))
    return scaled


def _arrangement_from_spec(
    name: str,
    spec: tuple[_SectionSpec, ...],
    *,
    tempo: float | None,
    total_bars: int | None,
) -> ArrangementPlan:
    """Build an :class:`ArrangementPlan` from a section ``spec``.

    Shared by every style preset. ``tempo`` (BPM) is carried onto the plan so
    ``build_job_plan`` emits a leading ``set_tempo`` step. ``total_bars`` rescales the
    whole arrangement to that length (``None`` keeps the spec's built-in lengths). Section
    start bars are always recomputed contiguously from bar 1, so the result is gap-free at
    any length.
    """
    if total_bars is not None and total_bars <= 0:
        raise ValueError("total_bars must be positive (got %d)" % total_bars)

    base_lengths = [length for _, _, _, length, _ in spec]
    lengths = (
        _scaled_lengths(base_lengths, total_bars)
        if total_bars is not None
        else base_lengths
    )

    sections: list[ArrangementSection] = []
    start_bar = 1
    for (section_id, display_name, source_scene, _base_length, transition), length in zip(
        spec, lengths
    ):
        sections.append(
            ArrangementSection(
                section_id=section_id,
                name=display_name,
                source_scene=source_scene,
                start_bar=start_bar,
                length_bars=length,
                transition=transition,
            )
        )
        start_bar += length
    return ArrangementPlan(name=name, sections=tuple(sections), tempo=tempo)


def simple_arrangement(
    name: str = DEFAULT_ARRANGEMENT_NAME,
    *,
    tempo: float | None = None,
    total_bars: int | None = None,
) -> ArrangementPlan:
    """Return the default dark-tech-house arrangement under ``name``.

    A valid, ready-to-use plan rather than a set of placeholders to fill in. The default
    (``tempo``/``total_bars`` unset) keeps the built-in tempo-less 56-bar layout.
    """
    return _arrangement_from_spec(
        name, _SIMPLE_SECTIONS, tempo=tempo, total_bars=total_bars
    )


def deep_house_arrangement(
    name: str = DEEP_HOUSE_DEFAULT_NAME,
    *,
    tempo: float | None = None,
    total_bars: int | None = None,
) -> ArrangementPlan:
    """Return the deep-house arrangement under ``name``.

    Smoother and warmer than dark-tech-house. Unlike that preset, deep-house ships opinion
    -ated defaults: 122 BPM and a 64-bar layout. An explicit ``tempo``/``total_bars`` (e.g.
    from ``--tempo``/``--bars``) overrides them; leaving them unset applies the defaults.
    """
    return _arrangement_from_spec(
        name,
        _DEEP_HOUSE_SECTIONS,
        tempo=DEEP_HOUSE_DEFAULT_TEMPO if tempo is None else tempo,
        total_bars=DEEP_HOUSE_DEFAULT_BARS if total_bars is None else total_bars,
    )


def minimal_techno_arrangement(
    name: str = MINIMAL_TECHNO_DEFAULT_NAME,
    *,
    tempo: float | None = None,
    total_bars: int | None = None,
) -> ArrangementPlan:
    """Return the minimal-techno arrangement under ``name``.

    More mechanical and repetitive than deep-house, more stripped back than
    dark-tech-house. Ships opinionated defaults: 126 BPM and a 64-bar layout. An explicit
    ``tempo``/``total_bars`` (e.g. from ``--tempo``/``--bars``) overrides them; leaving them
    unset applies the defaults.
    """
    return _arrangement_from_spec(
        name,
        _MINIMAL_TECHNO_SECTIONS,
        tempo=MINIMAL_TECHNO_DEFAULT_TEMPO if tempo is None else tempo,
        total_bars=MINIMAL_TECHNO_DEFAULT_BARS if total_bars is None else total_bars,
    )


def dub_techno_arrangement(
    name: str = DUB_TECHNO_DEFAULT_NAME,
    *,
    tempo: float | None = None,
    total_bars: int | None = None,
) -> ArrangementPlan:
    """Return the dub-techno arrangement under ``name``.

    Deep and spacey: echoing chords and delay swells over a sub-heavy groove -- more
    floating than minimal-techno, harder than deep-house. Ships opinionated defaults:
    124 BPM and a 64-bar layout. An explicit ``tempo``/``total_bars`` (e.g. from
    ``--tempo``/``--bars``) overrides them; leaving them unset applies the defaults.
    """
    return _arrangement_from_spec(
        name,
        _DUB_TECHNO_SECTIONS,
        tempo=DUB_TECHNO_DEFAULT_TEMPO if tempo is None else tempo,
        total_bars=DUB_TECHNO_DEFAULT_BARS if total_bars is None else total_bars,
    )


# --- style registry --------------------------------------------------------------

#: Builder signature shared by every style preset: ``(name, *, tempo, total_bars)``.
StyleBuilder = Callable[..., ArrangementPlan]


class UnknownStyleError(ValueError):
    """Raised when a caller asks for a style that has no registered preset.

    A subclass of ``ValueError`` carrying a message that lists the styles that *are*
    available, so the CLI can surface a clear, actionable failure.
    """


#: style name -> arrangement builder. New genres join by adding one entry here; nothing
#: else needs to change.
_STYLE_BUILDERS: dict[str, StyleBuilder] = {
    "dark-tech-house": simple_arrangement,
    "deep-house": deep_house_arrangement,
    "minimal-techno": minimal_techno_arrangement,
    "dub-techno": dub_techno_arrangement,
}


def available_styles() -> tuple[str, ...]:
    """Return the registered style names, in registration order."""
    return tuple(_STYLE_BUILDERS)


def _builder_for_style(style: str) -> StyleBuilder:
    """Return the registered builder for ``style`` or raise :class:`UnknownStyleError`."""
    try:
        return _STYLE_BUILDERS[style]
    except KeyError:
        raise UnknownStyleError(
            "unsupported style: %r (available: %s)"
            % (style, ", ".join(available_styles()))
        ) from None


def default_name_for_style(style: str) -> str:
    """Return the natural default arrangement name for ``style``.

    This is the name used when the CLI's ``--name`` is omitted, sourced from each builder's
    own default (e.g. ``dark_tech_house``, ``deep_house``) so there is a single source of
    truth per style. Raises :class:`UnknownStyleError` for an unregistered style.
    """
    builder = _builder_for_style(style)
    return builder().name


def arrangement_for_style(
    style: str,
    name: str | None = None,
    *,
    tempo: float | None = None,
    total_bars: int | None = None,
) -> ArrangementPlan:
    """Build the arrangement for ``style`` (one entry point for every genre preset).

    Delegates to the registered builder for ``style``, forwarding ``tempo``/``total_bars``.
    When ``name`` is ``None`` the builder's own style-specific default name is used (e.g.
    ``deep_house`` for deep-house); an explicit ``name`` overrides it. Raises
    :class:`UnknownStyleError` for an unregistered style.
    """
    builder = _builder_for_style(style)
    if name is None:
        return builder(tempo=tempo, total_bars=total_bars)
    return builder(name, tempo=tempo, total_bars=total_bars)
