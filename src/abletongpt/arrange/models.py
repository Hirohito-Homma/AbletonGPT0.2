from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArrangementSection:
    """A single named block of an arrangement, sourced from one Session scene."""

    section_id: str
    name: str
    source_scene: str
    start_bar: int
    length_bars: int
    transition: str = "none"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArrangementPlan:
    """An ordered, deterministic song structure. No Live mutation happens here."""

    name: str
    sections: tuple[ArrangementSection, ...] = ()
    #: Optional song tempo in BPM. ``None`` means "leave the Live Set's tempo alone";
    #: when set, ``build_job_plan`` emits a leading ``set_tempo`` step.
    tempo: float | None = None

    @property
    def total_bars(self) -> int:
        """Bars spanned from bar 0 to the end of the last section (0 when empty)."""
        if not self.sections:
            return 0
        return max(section.start_bar + section.length_bars for section in self.sections)
