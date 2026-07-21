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

# (section_id, name, source_scene, relative_length_bars, transition)
# Start bars are derived (contiguous, 1-based) rather than stored, so the layout can be
# rescaled to any total length while staying gap-free. The default lengths sum to 56.
_SIMPLE_SECTIONS: tuple[tuple[str, str, str, int, str], ...] = (
    ("intro", "Intro", "intro", 8, "none"),
    ("groove", "Groove", "groove", 16, "fill"),
    ("break", "Break", "break", 8, "break"),
    ("drop", "Drop", "drop", 16, "fill"),
    ("outro", "Outro", "outro", 8, "none"),
)


def _scaled_lengths(total_bars: int) -> list[int]:
    """Scale the default section lengths so they sum to exactly ``total_bars``.

    Every section keeps its relative weight (rounded, at least 1 bar); the final section
    absorbs the rounding remainder so the total lands on ``total_bars`` precisely.
    """
    base = [length for _, _, _, length, _ in _SIMPLE_SECTIONS]
    base_total = sum(base)
    scaled = [max(1, round(length * total_bars / base_total)) for length in base[:-1]]
    scaled.append(max(1, total_bars - sum(scaled)))
    return scaled


def simple_arrangement(
    name: str = DEFAULT_ARRANGEMENT_NAME,
    *,
    tempo: float | None = None,
    total_bars: int | None = None,
) -> ArrangementPlan:
    """Return the default dark-tech-house arrangement under ``name``.

    A valid, ready-to-use plan rather than a set of placeholders to fill in.
    ``tempo`` (BPM) is carried onto the plan so ``build_job_plan`` emits a leading
    ``set_tempo`` step. ``total_bars`` rescales the whole arrangement to that length; the
    default (``None``) keeps the built-in 56-bar layout. Section start bars are always
    recomputed contiguously from bar 1, so the result is gap-free at any length.
    """
    if total_bars is not None and total_bars <= 0:
        raise ValueError("total_bars must be positive (got %d)" % total_bars)

    lengths = (
        _scaled_lengths(total_bars)
        if total_bars is not None
        else [length for _, _, _, length, _ in _SIMPLE_SECTIONS]
    )

    sections: list[ArrangementSection] = []
    start_bar = 1
    for (section_id, display_name, source_scene, _base_length, transition), length in zip(
        _SIMPLE_SECTIONS, lengths
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


# --- style registry --------------------------------------------------------------

#: Builder signature shared by every style preset: ``(name, *, tempo, total_bars)``.
StyleBuilder = Callable[..., ArrangementPlan]


class UnknownStyleError(ValueError):
    """Raised when a caller asks for a style that has no registered preset.

    A subclass of ``ValueError`` carrying a message that lists the styles that *are*
    available, so the CLI can surface a clear, actionable failure.
    """


#: style name -> arrangement builder. New genres (``minimal-techno``, ``deep-house``,
#: ``dub-techno``, ...) join by adding one entry here; nothing else needs to change.
_STYLE_BUILDERS: dict[str, StyleBuilder] = {
    "dark-tech-house": simple_arrangement,
}


def available_styles() -> tuple[str, ...]:
    """Return the registered style names, in registration order."""
    return tuple(_STYLE_BUILDERS)


def arrangement_for_style(
    style: str,
    name: str = DEFAULT_ARRANGEMENT_NAME,
    *,
    tempo: float | None = None,
    total_bars: int | None = None,
) -> ArrangementPlan:
    """Build the arrangement for ``style`` (one entry point for every genre preset).

    Delegates to the registered builder for ``style``, forwarding ``name``/``tempo``/
    ``total_bars``. Raises :class:`UnknownStyleError` for an unregistered style.
    """
    try:
        builder = _STYLE_BUILDERS[style]
    except KeyError:
        raise UnknownStyleError(
            "unsupported style: %r (available: %s)"
            % (style, ", ".join(available_styles()))
        ) from None
    return builder(name, tempo=tempo, total_bars=total_bars)
