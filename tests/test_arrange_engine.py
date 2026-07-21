from __future__ import annotations

from abletongpt.arrange import (
    ArrangeEngine,
    ArrangementPlan,
    PlaceSceneOperation,
    build_operations,
)


def test_default_plan_identity_and_shape():
    plan = ArrangeEngine().dark_tech_house_default()
    assert plan.name == "dark_tech_house_default"
    assert len(plan.sections) == 7
    assert plan.total_bars == 144


def test_default_plan_first_and_last_section():
    plan = ArrangeEngine().dark_tech_house_default()

    first = plan.sections[0]
    assert first.name == "Intro"
    assert first.source_scene == "intro"
    assert first.start_bar == 0
    assert first.length_bars == 16

    last = plan.sections[-1]
    assert last.name == "Outro"
    assert last.source_scene == "outro"
    assert last.start_bar == 128
    assert last.length_bars == 16


def test_build_operations_returns_ordered_place_scene_operations():
    plan = ArrangeEngine().dark_tech_house_default()
    operations = build_operations(plan)

    assert isinstance(operations, list)
    assert len(operations) == len(plan.sections)
    assert all(isinstance(op, PlaceSceneOperation) for op in operations)

    for section, operation in zip(plan.sections, operations):
        assert operation.source_scene == section.source_scene
        assert operation.start_bar == section.start_bar
        assert operation.length_bars == section.length_bars
        assert operation.transition == section.transition


def test_build_operations_first_operation_matches_intro():
    plan = ArrangeEngine().dark_tech_house_default()
    first = build_operations(plan)[0]
    assert first == PlaceSceneOperation(
        source_scene="intro",
        start_bar=0,
        length_bars=16,
        transition="none",
    )


def test_engine_is_deterministic():
    engine = ArrangeEngine()
    assert engine.dark_tech_house_default() == engine.dark_tech_house_default()


def test_empty_plan_total_bars_is_zero():
    assert ArrangementPlan(name="empty").total_bars == 0
    assert build_operations(ArrangementPlan(name="empty")) == []
