"""Shared JSON <-> model helpers for the CLI entry points.

Kept deliberately small: only the arrangement (de)serialization and the UTF-8/indent
conventions that ``cli.arrange`` and ``cli.jobs`` both need. Job-plan (de)serialization
already lives in :mod:`abletongpt.jobs.store`; this module does not duplicate it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..arrange.models import ArrangementPlan, ArrangementSection


def arrangement_from_dict(document: dict[str, Any]) -> ArrangementPlan:
    """Reconstruct an :class:`ArrangementPlan` from a plain JSON document.

    Mirrors the model's fields exactly; ``transition`` and ``tags`` fall back to the
    dataclass defaults when omitted. Missing required keys raise ``KeyError`` and
    non-numeric bars raise ``ValueError`` — callers that validate untrusted input
    should catch these.
    """
    sections = tuple(
        ArrangementSection(
            section_id=raw["section_id"],
            name=raw["name"],
            source_scene=raw["source_scene"],
            start_bar=int(raw["start_bar"]),
            length_bars=int(raw["length_bars"]),
            transition=raw.get("transition", "none"),
            tags=tuple(raw.get("tags", ())),
        )
        for raw in document.get("sections", [])
    )
    return ArrangementPlan(name=document["name"], sections=sections)


def arrangement_to_dict(plan: ArrangementPlan) -> dict[str, Any]:
    """Serialize an :class:`ArrangementPlan` to a JSON-ready dict.

    Round-trips with :func:`arrangement_from_dict`.
    """
    return {
        "name": plan.name,
        "sections": [
            {
                "section_id": section.section_id,
                "name": section.name,
                "source_scene": section.source_scene,
                "start_bar": section.start_bar,
                "length_bars": section.length_bars,
                "transition": section.transition,
                "tags": list(section.tags),
            }
            for section in plan.sections
        ],
    }


def read_json_document(path: str | Path) -> Any:
    """Read and parse a UTF-8 JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json_document(document: Any, path: str | Path) -> Path:
    """Write ``document`` as pretty UTF-8 JSON, creating parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path
