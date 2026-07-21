from __future__ import annotations

from .models import ArrangementPlan, ArrangementSection


# Deterministic Dark Tech House template: Intro/Groove/Build/Drop/Break/Final Drop/Outro.
# (section_id, name, source_scene, start_bar, length_bars, transition)
_DARK_TECH_HOUSE_SECTIONS: tuple[tuple[str, str, str, int, int, str], ...] = (
    ("intro", "Intro", "intro", 0, 16, "none"),
    ("groove", "Groove", "groove", 16, 16, "fill"),
    ("build", "Build", "build", 32, 16, "riser"),
    ("drop", "Drop", "drop", 48, 32, "fill"),
    ("break", "Break", "break", 80, 16, "break"),
    ("final_drop", "Final Drop", "final_drop", 96, 32, "fill"),
    ("outro", "Outro", "outro", 128, 16, "none"),
)


class ArrangeEngine:
    """Produces deterministic arrangement plans. No Live connection or randomness."""

    def dark_tech_house_default(self) -> ArrangementPlan:
        """Return the canonical Dark Tech House arrangement (144 total bars)."""
        sections = tuple(
            ArrangementSection(
                section_id=section_id,
                name=name,
                source_scene=source_scene,
                start_bar=start_bar,
                length_bars=length_bars,
                transition=transition,
            )
            for section_id, name, source_scene, start_bar, length_bars, transition in (
                _DARK_TECH_HOUSE_SECTIONS
            )
        )
        return ArrangementPlan(name="dark_tech_house_default", sections=sections)
