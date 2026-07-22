from __future__ import annotations

from abletongpt.arrange import (
    ArrangeEngine,
    ArrangementPlan,
    PlaceSceneOperation,
    arrangement_for_style,
    available_styles,
    build_operations,
    pop_song_arrangement,
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


# --- pop song-form template ------------------------------------------------------

def test_pop_song_is_a_registered_style():
    assert "pop-song" in available_styles()
    assert arrangement_for_style("pop-song") == pop_song_arrangement()


def test_pop_song_shape_and_defaults():
    plan = pop_song_arrangement()
    assert plan.name == "pop_song"
    assert plan.tempo == 100.0
    # 64 bars of content, laid out contiguously from bar 1 (like the other presets).
    assert sum(section.length_bars for section in plan.sections) == 64
    ids = [section.section_id for section in plan.sections]
    assert ids == [
        "intro",
        "verse_1",
        "pre_chorus_1",
        "chorus_1",
        "verse_2",
        "pre_chorus_2",
        "chorus_2",
        "bridge",
        "chorus_3",
        "outro",
    ]


def test_pop_song_repeats_reuse_one_source_scene():
    by_id = {section.section_id: section for section in pop_song_arrangement().sections}
    assert by_id["verse_1"].source_scene == by_id["verse_2"].source_scene == "verse"
    assert (
        by_id["chorus_1"].source_scene
        == by_id["chorus_2"].source_scene
        == by_id["chorus_3"].source_scene
        == "chorus"
    )


def test_pop_song_sections_are_contiguous_and_gap_free():
    sections = pop_song_arrangement().sections
    expected_start = 1
    for section in sections:
        assert section.start_bar == expected_start
        expected_start += section.length_bars


def test_pop_song_rescales_to_a_custom_length():
    plan = pop_song_arrangement(total_bars=128)
    # Rescaling makes the section lengths sum to the requested total.
    assert sum(section.length_bars for section in plan.sections) == 128
    # Still ten contiguous sections after rescaling.
    assert len(plan.sections) == 10
