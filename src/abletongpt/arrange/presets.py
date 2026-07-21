"""Ready-made :class:`ArrangementPlan` factories shared across the CLI.

The default is a compact dark-tech-house layout: a contiguous intro -> outro song
structure whose ``section_id``/``source_scene`` use the same lowercase vocabulary the
Arrange Engine emits, so :func:`~abletongpt.jobs.build_job_plan` maps it cleanly. Bars
are 1-based and positive so the result passes ``cli.arrange validate`` as-is.

Both ``cli.arrange create-simple`` and ``cli.jobs arrange-run`` build their default
arrangement from here, so the two entry points can never drift apart.
"""

from __future__ import annotations

from .models import ArrangementPlan, ArrangementSection

#: Name used when a caller does not supply one (e.g. ``arrange-run`` with no ``--name``).
DEFAULT_ARRANGEMENT_NAME = "dark_tech_house"

# (section_id, name, source_scene, start_bar, length_bars, transition)
_SIMPLE_SECTIONS: tuple[tuple[str, str, str, int, int, str], ...] = (
    ("intro", "Intro", "intro", 1, 8, "none"),
    ("groove", "Groove", "groove", 9, 16, "fill"),
    ("break", "Break", "break", 25, 8, "break"),
    ("drop", "Drop", "drop", 33, 16, "fill"),
    ("outro", "Outro", "outro", 49, 8, "none"),
)


def simple_arrangement(name: str = DEFAULT_ARRANGEMENT_NAME) -> ArrangementPlan:
    """Return the default dark-tech-house arrangement under ``name``.

    A valid, ready-to-use plan rather than a set of placeholders to fill in.
    """
    sections = tuple(
        ArrangementSection(
            section_id=section_id,
            name=display_name,
            source_scene=source_scene,
            start_bar=start_bar,
            length_bars=length_bars,
            transition=transition,
        )
        for section_id, display_name, source_scene, start_bar, length_bars, transition in (
            _SIMPLE_SECTIONS
        )
    )
    return ArrangementPlan(name=name, sections=sections)
