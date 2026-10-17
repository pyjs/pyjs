"""Executable specification for column-container masonry mechanics.

The sections progress from layout and legal destinations through previews,
native clipping, multi-step journeys, viewport anchoring, representative
geometry invariants, and resilient API boundaries. These are geometry contracts, not a calibrated model of RecyclerView.
Real layout-manager behavior needs its own Android integration tests.
"""

import pytest

from pyjs.ui.masonry import (
    MasonryDragDecision,
    MasonryDragSession,
    MasonryDragSimulator,
    MasonryItemGeometry,
    MasonryLayoutSnapshot,
    MasonryViewport,
    NativeRect,
)

pytestmark = pytest.mark.pyjs_python


def items(
    heights: list[float],
    groups: list[str] | None = None,
) -> list[MasonryItemGeometry]:
    result = []
    for index, height in enumerate(heights):
        group = "notes" if groups is None else groups[index]
        result.append(
            MasonryItemGeometry(
                str(index),
                100,
                height,
                height,
                group,
            )
        )
    return result


def viewport(scroll: float = 0, maximum: float = 2_000) -> MasonryViewport:
    return MasonryViewport(10, 100, 220, 400, scroll, maximum)


def drag_session(
    simulator: MasonryDragSimulator,
    values: list[MasonryItemGeometry],
    source_index: int,
    active_viewport: MasonryViewport,
    original_layout=None,
) -> MasonryDragSession:
    layout = simulator.layout(values) if original_layout is None else original_layout
    source = layout.rects[source_index]
    session = simulator.begin_drag(
        values,
        source_index,
        active_viewport,
        active_viewport.screen_x + source.x + 10,
        active_viewport.screen_y + source.y - active_viewport.scroll_offset + 10,
        layout,
    )
    assert isinstance(session, MasonryDragSession)
    return session


def drag_to_slot(
    simulator: MasonryDragSimulator,
    session: MasonryDragSession,
    active_viewport: MasonryViewport,
    destination_index: int,
    destination_column: int | None = None,
) -> MasonryDragDecision:
    slots = session.slots
    slot = next(
        slot
        for slot in slots
        if slot.destination_index == destination_index
        and (
            destination_column is None
            or slot.destination_column == destination_column
        )
    )
    return simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + slot.source_rect.x + session.grab_x,
        active_viewport.screen_y
        + slot.source_rect.y
        - active_viewport.scroll_offset
        + session.grab_y,
    )


def drag_to_lane(
    simulator: MasonryDragSimulator,
    session: MasonryDragSession,
    active_viewport: MasonryViewport,
    destination_column: int,
    destination_lane_index: int,
) -> MasonryDragDecision:
    slots = session.slots
    slot = next(
        slot
        for slot in slots
        if slot.destination_column == destination_column
        and slot.destination_lane_index == destination_lane_index
    )
    return simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + slot.source_rect.x + session.grab_x,
        active_viewport.screen_y
        + slot.source_rect.y
        - active_viewport.scroll_offset
        + session.grab_y,
    )


# Layout and legal destinations


def test_layout_uses_shortest_placement_column_and_real_item_heights():
    simulator = MasonryDragSimulator([0, 110], vertical_gap=10)
    values = [
        MasonryItemGeometry("a", 100, 40, 100),
        MasonryItemGeometry("b", 100, 180, 50),
        MasonryItemGeometry("c", 100, 60, 20),
        MasonryItemGeometry("d", 100, 30, 90),
    ]

    layout = simulator.layout(values)

    assert layout.columns == [0, 1, 1, 1]
    assert [(rect.x, rect.y, rect.width, rect.height) for rect in layout.rects] == [
        (0, 0, 100, 40),
        (110, 0, 100, 180),
        (110, 190, 100, 60),
        (110, 260, 100, 30),
    ]
    assert layout.content_height == 290


def test_explicit_layout_uses_shortest_lane_for_missing_or_invalid_hints():
    simulator = MasonryDragSimulator([0, 110], vertical_gap=10)
    values = [
        MasonryItemGeometry("a", 100, 40, 100),
        MasonryItemGeometry("b", 100, 180, 200),
        MasonryItemGeometry("c", 100, 60, 20),
        MasonryItemGeometry("d", 100, 30, 90),
    ]

    layout = simulator.layout_in_columns(values, [1, -1, 99])

    assert layout.columns == [1, 0, 1, 1]
    assert [(rect.x, rect.y) for rect in layout.rects] == [
        (110, 0),
        (0, 0),
        (110, 50),
        (110, 120),
    ]


def test_group_runs_start_below_the_tallest_preceding_column():
    simulator = MasonryDragSimulator(
        [0, 110],
        vertical_gap=10,
        group_gap=16,
    )
    values = [
        MasonryItemGeometry("pinned-short", 100, 40, 100, "pinned"),
        MasonryItemGeometry("pinned-tall", 100, 80, 50, "pinned"),
        MasonryItemGeometry("note-a", 100, 30, 30, "notes"),
        MasonryItemGeometry("note-b", 100, 20, 20, "notes"),
    ]

    layout = simulator.layout_in_columns(values, [0, 1, 0, 1])

    assert layout.columns == [0, 1, 0, 1]
    assert [(rect.x, rect.y) for rect in layout.rects] == [
        (0, 0),
        (110, 0),
        (0, 106),
        (110, 106),
    ]


def test_drag_visual_stays_inside_its_group_section():
    simulator = MasonryDragSimulator([0, 110], group_gap=16, hysteresis=0)
    values = [
        MasonryItemGeometry("pinned-a", 100, 80, 80, "pinned"),
        MasonryItemGeometry("pinned-b", 100, 180, 180, "pinned"),
        MasonryItemGeometry("note-a", 100, 40, 40, "notes"),
        MasonryItemGeometry("note-b", 100, 60, 60, "notes"),
    ]
    original = simulator.layout(values)
    active_viewport = viewport()
    session = drag_session(simulator, values, 2, active_viewport)

    decision = simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + 120,
        active_viewport.screen_y + 10,
    )
    source = original.rect_for("note-a")
    pinned = original.rect_for("pinned-b")
    assert source is not None and pinned is not None
    assert source.y + decision.translate_y[2] == 196
    assert source.y + decision.translate_y[2] > pinned.bottom
    pinned_after = decision.preview_layout.rect_for("pinned-b")
    assert pinned_after is not None
    assert (pinned_after.x, pinned_after.y) == (pinned.x, pinned.y)
    note_b = original.rect_for("note-b")
    note_b_after = decision.preview_layout.rect_for("note-b")
    assert note_b is not None and note_b_after is not None
    assert note_b_after.y == note_b.y + source.height


@pytest.mark.parametrize("columns", [1, 2, 3, 4])
@pytest.mark.parametrize(
    "heights",
    [
        [48, 48, 48, 48, 48],
        [24, 220, 32, 180, 40],
        [600, 20, 20, 20, 20],
        [31, 47, 89, 163, 277],
    ],
)
def test_every_drop_slot_is_reachable_at_its_exact_geometry(columns, heights):
    simulator = MasonryDragSimulator(
        [float(index * 110) for index in range(columns)],
        vertical_gap=8,
        hysteresis=0,
    )
    values = items(heights)
    layout = simulator.layout(values)
    active_viewport = MasonryViewport(0, 0, columns * 110, 10_000, 0, 0)

    for source_index in range(len(values)):
        source_rect = layout.rects[source_index]
        session = simulator.begin_drag(
            values,
            source_index,
            active_viewport,
            source_rect.x + 7,
            source_rect.y + 9,
        )
        for slot in simulator.drop_slots(values, source_index):
            session.destination_index = -1
            decision = simulator.advance_drag(
                session,
                active_viewport,
                slot.source_rect.x + 7,
                slot.source_rect.y + 9,
            )
            assert decision.destination_index == slot.destination_index


def test_dense_small_cards_have_distinct_between_card_destinations():
    simulator = MasonryDragSimulator([0, 110], vertical_gap=8, hysteresis=0)
    values = items([32, 34, 28, 36, 30, 38, 26, 40])
    slots = simulator.drop_slots(values, 7)

    assert [
        (slot.destination_column, slot.destination_lane_index)
        for slot in slots
    ] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (0, 3),
        (0, 4),
        (1, 0),
        (1, 1),
        (1, 2),
        (1, 3),
    ]
    assert len({(slot.source_rect.x, slot.source_rect.y) for slot in slots}) == 9


def test_spatial_slots_include_both_sides_of_an_oversized_neighbor():
    simulator = MasonryDragSimulator([0, 110], vertical_gap=8, hysteresis=0)
    values = items([30, 400, 30, 30, 30, 30])
    original = simulator.layout(values)

    slots = simulator.drop_slots(values, 0, original)
    right_slots = [
        slot.source_rect.y
        for slot in slots
        if slot.destination_column == 1
    ]

    assert right_slots == [0, 408]
    assert all(not 0 < y < 408 for y in right_slots)


def test_group_boundaries_allow_every_slot_inside_group_but_never_cross_it():
    simulator = MasonryDragSimulator([0, 110])
    values = items(
        [40, 40, 40, 40, 40, 40],
        ["pinned", "pinned", "pinned", "notes", "notes", "notes"],
    )

    for source_index in range(len(values)):
        source_group = values[source_index].group
        for slot in simulator.drop_slots(values, source_index):
            layout = simulator.layout_for_slot(values, source_index, slot)
            source_position = layout.index_of(values[source_index].id)
            assert source_position >= 0
            assert values[source_index].group == source_group
            ordered_groups = [
                next(item.group for item in values if item.id == item_id)
                for item_id in layout.item_ids
            ]
            assert ordered_groups == [
                "pinned",
                "pinned",
                "pinned",
                "notes",
                "notes",
                "notes",
            ]


def test_repeated_group_names_remain_separate_contiguous_runs():
    simulator = MasonryDragSimulator([0, 110])
    values = items(
        [40, 40, 40, 40, 40],
        ["notes", "notes", "archive", "notes", "notes"],
    )
    run_by_id = {"0": 0, "1": 0, "2": 1, "3": 2, "4": 2}

    for source_index in range(len(values)):
        for slot in simulator.drop_slots(values, source_index):
            layout = simulator.layout_for_slot(values, source_index, slot)
            assert [run_by_id[item_id] for item_id in layout.item_ids] == [
                0,
                0,
                1,
                2,
                2,
            ]


def test_lazy_slot_metadata_matches_materialized_margin_and_group_layouts():
    simulator = MasonryDragSimulator([0, 130, 260], vertical_gap=9)
    values = [
        MasonryItemGeometry("a", 100, 37, 42, "notes", 2, 0, 3, 4),
        MasonryItemGeometry("b", 100, 83, 89, "notes", 5, 0, 7, 1),
        MasonryItemGeometry("c", 100, 29, 35, "archive", 3, 0, 2, 6),
        MasonryItemGeometry("d", 100, 61, 70, "notes", 1, 0, 8, 2),
        MasonryItemGeometry("e", 100, 47, 53, "notes", 4, 0, 5, 3),
    ]
    original = simulator.layout(values)

    for source_index in range(len(values)):
        for slot in simulator.drop_slots(values, source_index, original):
            layout = simulator.layout_for_slot(
                values,
                source_index,
                slot,
                original,
            )
            layout_index = layout.index_of(values[source_index].id)
            rect = layout.rects[layout_index]
            assert slot.destination_index == layout_index
            assert (
                slot.source_rect.x,
                slot.source_rect.y,
                slot.source_rect.width,
                slot.source_rect.height,
            ) == (rect.x, rect.y, rect.width, rect.height)


def test_drag_session_reuses_its_precomputed_drop_slots(monkeypatch):
    simulator = MasonryDragSimulator([0, 110], hysteresis=0)
    values = items([40, 80, 120, 160])
    active_viewport = viewport()
    session = drag_session(simulator, values, 0, active_viewport)
    target = session.slots[-1]

    def unexpected_recalculation(*_args, **_kwargs):
        raise AssertionError("drop slots must remain invariant during a drag")

    monkeypatch.setattr(simulator, "drop_slots", unexpected_recalculation)

    decision = simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + target.source_rect.x + session.grab_x,
        active_viewport.screen_y + target.source_rect.y + session.grab_y,
    )

    assert decision.destination_index == target.destination_index


def test_drop_slot_previews_are_materialized_only_after_selection(monkeypatch):
    simulator = MasonryDragSimulator([0, 110], hysteresis=0)
    values = items([40, 80, 120, 160])
    active_viewport = viewport()
    canonical_layout = simulator._canonical_layout
    layout_calls = 0

    def measured_layout(*args):
        nonlocal layout_calls
        layout_calls += 1
        return canonical_layout(*args)

    monkeypatch.setattr(simulator, "_canonical_layout", measured_layout)
    session = drag_session(simulator, values, 0, active_viewport)
    assert layout_calls == 0

    first = session.slots[0]
    simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + first.source_rect.x + session.grab_x,
        active_viewport.screen_y + first.source_rect.y + session.grab_y,
    )
    assert layout_calls == 1

    simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + first.source_rect.x + session.grab_x,
        active_viewport.screen_y + first.source_rect.y + session.grab_y,
    )
    assert layout_calls == 1

    last = session.slots[-1]
    simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + last.source_rect.x + session.grab_x,
        active_viewport.screen_y + last.source_rect.y + session.grab_y,
    )
    assert layout_calls == 2


@pytest.mark.parametrize("item_count", [100, 200])
def test_drop_slot_geometry_selection_scales_with_items_times_columns(
    monkeypatch,
    item_count,
):
    simulator = MasonryDragSimulator([0, 110, 220, 330], vertical_gap=8)
    values = items([30 + index % 17 for index in range(item_count)])
    original = simulator.layout(values)
    rect_reads = 0
    layout_calls = 0
    layout_in_columns = simulator.layout_in_columns

    class CountingRects(list):
        def __getitem__(self, index):
            nonlocal rect_reads
            rect_reads += 1
            return super().__getitem__(index)

    def measured_layout(candidate_items, columns, group_runs=None):
        nonlocal layout_calls
        layout_calls += 1
        snapshot = layout_in_columns(candidate_items, columns, group_runs)
        snapshot.rects = CountingRects(snapshot.rects)
        return snapshot

    monkeypatch.setattr(simulator, "layout_in_columns", measured_layout)

    slots = simulator.drop_slots(values, item_count // 3, original)

    column_count = len(simulator.column_lefts)
    assert layout_calls == 1
    assert rect_reads <= len(slots) * item_count * column_count
    legacy_selection_reads = len(slots) * item_count * (item_count + 1) // 2
    assert legacy_selection_reads >= rect_reads * 5


# Drag selection and exact previews


def test_same_column_preview_keeps_the_opposite_column_stable():
    simulator = MasonryDragSimulator(
        [0, 519],
        vertical_gap=42,
        hysteresis=0,
    )
    values = [
        MasonryItemGeometry("tiny", 477, 256, 336, "pinned"),
        MasonryItemGeometry("books", 477, 1_033, 702, "pinned"),
        MasonryItemGeometry("checklist", 477, 502, 486, "pinned"),
        MasonryItemGeometry("travel", 477, 269, 336, "pinned"),
    ]
    original = simulator.layout(values)
    active_viewport = MasonryViewport(21, 386, 1_038, 1_770, 0, 1_000)
    session = drag_session(simulator, values, 2, active_viewport)

    decision = drag_to_slot(simulator, session, active_viewport, 0)

    assert original.columns == [0, 1, 0, 1]
    assert decision.preview_layout.item_ids == [
        "checklist",
        "books",
        "tiny",
        "travel",
    ]
    assert decision.preview_layout.columns == [0, 1, 0, 1]
    for item_id in ("books", "travel"):
        before = original.rect_for(item_id)
        after = decision.preview_layout.rect_for(item_id)
        assert before is not None and after is not None
        assert (after.x, after.y) == (before.x, before.y)
    tiny = decision.preview_layout.rect_for("tiny")
    assert tiny is not None
    assert (tiny.x, tiny.y) == (0, 544)


def test_lane_order_stays_explicit_when_greedy_columns_cannot_represent_it():
    simulator = MasonryDragSimulator([0, 110])
    values = items([20, 20, 20, 20, 100])
    original = simulator.layout(values)
    active_viewport = viewport()
    session = drag_session(simulator, values, 4, active_viewport)

    decision = drag_to_slot(simulator, session, active_viewport, 0)

    assert original.columns == [0, 1, 0, 1, 0]
    assert decision.preview_layout.item_ids == ["4", "1", "3", "0", "2"]
    assert decision.preview_layout.columns == [0, 1, 1, 0, 0]
    for item_id in ("1", "3"):
        before = original.rect_for(item_id)
        after = decision.preview_layout.rect_for(item_id)
        assert before is not None and after is not None
        assert (after.x, after.y) == (before.x, before.y)


def test_two_consecutive_same_lane_drags_keep_the_other_lane_stable():
    simulator = MasonryDragSimulator(
        [0, 519],
        vertical_gap=42,
        hysteresis=0,
    )
    values = [
        MasonryItemGeometry("tiny", 477, 256, 336, "pinned"),
        MasonryItemGeometry("books", 477, 1_033, 702, "pinned"),
        MasonryItemGeometry("travel", 477, 269, 336, "pinned"),
        MasonryItemGeometry("checklist", 477, 502, 486, "pinned"),
        MasonryItemGeometry("nine", 477, 928, 972, "pinned"),
        MasonryItemGeometry("six", 477, 700, 756, "pinned"),
    ]
    active_viewport = MasonryViewport(21, 386, 1_038, 1_770, 0, 1_000)
    original = simulator.layout(values)
    first_session = drag_session(simulator, values, 2, active_viewport)

    downward = simulator.advance_drag(first_session, active_viewport, 200, 814)
    for desired_y in range(298, 843, 25):
        downward = simulator.advance_drag(
            first_session,
            active_viewport,
            active_viewport.screen_x + first_session.grab_x,
            active_viewport.screen_y + desired_y + first_session.grab_y,
        )
        travel_index = downward.preview_layout.index_of("travel")
        assert downward.preview_layout.columns[travel_index] == 0
        for item_id in ("books", "nine"):
            before = original.rect_for(item_id)
            after = downward.preview_layout.rect_for(item_id)
            assert before is not None and after is not None
            assert (after.x, after.y) == (before.x, before.y)

    assert downward.destination_index == 3
    assert downward.preview_layout.item_ids == [
        "tiny",
        "books",
        "checklist",
        "travel",
        "nine",
        "six",
    ]
    assert downward.preview_layout.columns == [0, 1, 0, 0, 1, 0]
    for item_id in ("books", "nine"):
        before = original.rect_for(item_id)
        after = downward.preview_layout.rect_for(item_id)
        assert before is not None and after is not None
        assert (after.x, after.y) == (before.x, before.y)

    values_by_id = {item.id: item for item in values}
    values = [values_by_id[item_id] for item_id in downward.preview_layout.item_ids]
    travel_index = downward.preview_layout.index_of("travel")
    travel_rect = downward.preview_layout.rect_for("travel")
    assert travel_rect is not None
    second_session = simulator.begin_drag(
        values,
        travel_index,
        active_viewport,
        active_viewport.screen_x + travel_rect.x + 10,
        active_viewport.screen_y + travel_rect.y + 10,
        downward.preview_layout,
    )
    assert isinstance(second_session, MasonryDragSession)

    upward = simulator.advance_drag(second_session, active_viewport, 10, 10)
    for desired_y in range(842, -1, -25):
        upward = simulator.advance_drag(
            second_session,
            active_viewport,
            active_viewport.screen_x + second_session.grab_x,
            active_viewport.screen_y + desired_y + second_session.grab_y,
        )
        travel_index = upward.preview_layout.index_of("travel")
        assert upward.preview_layout.columns[travel_index] == 0
        for item_id in ("books", "nine"):
            before = downward.preview_layout.rect_for(item_id)
            after = upward.preview_layout.rect_for(item_id)
            assert before is not None and after is not None
            assert (after.x, after.y) == (before.x, before.y)

    assert upward.destination_index == 0
    assert upward.preview_layout.item_ids == [
        "travel",
        "books",
        "tiny",
        "checklist",
        "nine",
        "six",
    ]
    assert upward.preview_layout.columns == [0, 1, 0, 0, 1, 0]
    for item_id in ("books", "nine"):
        before = downward.preview_layout.rect_for(item_id)
        after = upward.preview_layout.rect_for(item_id)
        assert before is not None and after is not None
        assert (after.x, after.y) == (before.x, before.y)


def test_preview_translations_land_every_sibling_on_the_committed_layout():
    simulator = MasonryDragSimulator([0, 110], vertical_gap=10, hysteresis=0)
    values = items([60, 180, 45, 90, 240, 35])
    original = simulator.layout(values)
    active_viewport = viewport()
    source_index = 0
    source_rect = original.rects[source_index]
    session = simulator.begin_drag(
        values,
        source_index,
        active_viewport,
        active_viewport.screen_x + source_rect.x + 10,
        active_viewport.screen_y + source_rect.y + 10,
    )
    target = simulator.drop_slots(values, source_index)[-1]

    decision = simulator.advance_drag(
        session,
        active_viewport,
        active_viewport.screen_x + target.source_rect.x + 10,
        active_viewport.screen_y + target.source_rect.y + 10,
    )

    for index, item in enumerate(values):
        if index == source_index:
            continue
        before = original.rect_for(item.id)
        after = decision.preview_layout.rect_for(item.id)
        assert before is not None
        assert after is not None
        assert before.x + decision.translate_x[index] == after.x
        assert before.y + decision.translate_y[index] == after.y


def test_hysteresis_keeps_current_slot_until_pointer_moves_decisively():
    simulator = MasonryDragSimulator([0], vertical_gap=0, hysteresis=15)
    values = items([40, 40, 40])
    active_viewport = viewport()
    session = simulator.begin_drag(values, 0, active_viewport, 20, 120)

    first = simulator.advance_drag(session, active_viewport, 20, 120)
    assert first.destination_index == 0
    near_boundary = simulator.advance_drag(session, active_viewport, 20, 142)
    assert near_boundary.destination_index == 0
    beyond_boundary = simulator.advance_drag(session, active_viewport, 20, 165)
    assert beyond_boundary.destination_index == 1


def test_pointer_column_wins_when_another_lane_has_a_closer_vertical_gap():
    simulator = MasonryDragSimulator(
        [0, 110, 220, 330],
        edge_size=0,
        hysteresis=0,
    )
    values = items([50, 50, 900])
    original = simulator.layout_in_columns(values, [0, 2, 3])
    active_viewport = MasonryViewport(0, 0, 440, 1_000, 0, 0)
    session = drag_session(
        simulator,
        values,
        0,
        active_viewport,
        original,
    )

    decision = simulator.advance_drag(session, active_viewport, 340, 460)

    assert decision.destination_column == 3


@pytest.mark.parametrize(
    ("pointer_y", "scroll", "maximum", "expected"),
    [
        (100, 50, 500, 26),
        (120, 0, 500, 0),
        (300, 50, 500, 50),
        (450, 50, 500, 55.25),
        (490, 50, 500, 70.25),
        (500, 50, 500, 74),
        (500, 500, 500, 500),
    ],
)
def test_edge_scrolling_is_exact_and_bounded(pointer_y, scroll, maximum, expected):
    simulator = MasonryDragSimulator([0, 110])
    active_viewport = MasonryViewport(0, 100, 220, 400, scroll, maximum)

    assert simulator.edge_scroll_offset(active_viewport, pointer_y) == expected


def test_pointer_content_position_accounts_for_edge_scrolling():
    simulator = MasonryDragSimulator([0], edge_step=24, hysteresis=0)
    values = items([100, 100])
    active_viewport = MasonryViewport(0, 100, 100, 200, 50, 300)
    session = simulator.begin_drag(values, 0, active_viewport, 10, 160)

    decision = simulator.advance_drag(session, active_viewport, 10, 295)

    assert decision.scroll_offset == 72.125
    assert decision.translate_y[0] == 157.125


def test_edge_scroll_amount_depends_on_elapsed_time_not_event_count():
    simulator = MasonryDragSimulator([0], edge_step=24, edge_interval_ms=50)
    one_update = MasonryViewport(0, 100, 100, 200, 50, 300)
    many_updates = MasonryViewport(0, 100, 100, 200, 50, 300)

    one_update.scroll_offset = simulator.edge_scroll_offset(
        one_update,
        295,
        50,
    )
    for _step in range(10):
        many_updates.scroll_offset = simulator.edge_scroll_offset(
            many_updates,
            295,
            5,
        )

    assert one_update.scroll_offset == 72.125
    assert many_updates.scroll_offset == pytest.approx(one_update.scroll_offset)


# Native projection and clipping


def test_projection_detects_android_column_clipping_around_a_huge_note():
    simulator = MasonryDragSimulator([0, 110], edge_size=0, hysteresis=0)
    values = items([300, 100, 100, 900, 60, 80])
    active_viewport = MasonryViewport(0, 100, 220, 400, 150, 700)
    session = drag_session(simulator, values, 4, active_viewport)

    decision = drag_to_slot(simulator, session, active_viewport, 3)
    clipped = simulator.project_preview(
        session,
        decision,
        active_viewport,
        clip_columns=True,
    )
    unclipped = simulator.project_preview(
        session,
        decision,
        active_viewport,
        clip_columns=False,
    )

    dragged_with_native_default = clipped.item_for("4")
    dragged_with_adapter_policy = unclipped.item_for("4")
    huge_note_with_native_default = clipped.item_for("3")
    huge_note_with_adapter_policy = unclipped.item_for("3")
    assert dragged_with_native_default is not None
    assert dragged_with_adapter_policy is not None
    assert huge_note_with_native_default is not None
    assert huge_note_with_adapter_policy is not None
    assert dragged_with_native_default.crosses_columns
    assert not dragged_with_native_default.center_is_visible
    assert dragged_with_adapter_policy.center_is_visible
    assert huge_note_with_native_default.is_visible
    assert huge_note_with_adapter_policy.is_visible


def test_projection_still_clips_cards_at_the_scroll_viewport():
    simulator = MasonryDragSimulator([0], edge_size=0, hysteresis=0)
    values = items([100, 100, 100])
    active_viewport = MasonryViewport(0, 0, 100, 100, 100, 200)
    session = drag_session(simulator, values, 1, active_viewport)
    decision = drag_to_slot(simulator, session, active_viewport, 1)

    projection = simulator.project_preview(
        session,
        decision,
        active_viewport,
        clip_columns=False,
    )

    above = projection.item_for("0")
    visible = projection.item_for("1")
    below = projection.item_for("2")
    assert above is not None and not above.is_visible
    assert visible is not None and visible.center_is_visible
    assert below is not None and not below.is_visible


def test_unclipped_projection_keeps_a_cross_lane_drag_visible():
    simulator = MasonryDragSimulator([0, 110], edge_size=0, hysteresis=0)
    values = items([60, 900, 80, 70, 90, 60, 100])
    active_viewport = MasonryViewport(0, 0, 220, 1_000, 0, 0)
    session = drag_session(simulator, values, 0, active_viewport)
    decision = drag_to_slot(simulator, session, active_viewport, 1)

    clipped = simulator.project_preview(session, decision, active_viewport)
    unclipped = simulator.project_preview(
        session,
        decision,
        active_viewport,
        clip_columns=False,
    )
    crossing_ids = [
        item.item_id
        for item in unclipped.items
        if item.crosses_columns and item.visual_rect.bottom <= active_viewport.height
    ]

    assert crossing_ids == ["0"]
    for item_id in crossing_ids:
        native_default = clipped.item_for(item_id)
        adapter_projection = unclipped.item_for(item_id)
        assert native_default is not None
        assert adapter_projection is not None
        assert not native_default.center_is_visible
        assert adapter_projection.center_is_visible


# Multi-step journeys


def test_four_column_tablet_drag_journey_from_bottom_left_to_top_then_bottom_right():
    simulator = MasonryDragSimulator(
        [0, 110, 220, 330],
        vertical_gap=8,
        edge_size=64,
        edge_step=24,
        hysteresis=0,
    )
    values = items(
        [
            60,
            900,
            80,
            70,
            90,
            60,
            100,
            140,
            50,
            180,
            65,
            120,
            75,
            200,
            55,
            160,
            85,
            220,
            95,
            130,
        ]
    )
    layout = simulator.layout(values)
    maximum_scroll = layout.content_height - 400
    active_viewport = MasonryViewport(0, 0, 440, 400, maximum_scroll, maximum_scroll)
    bottom_left = max(
        (
            index
            for index, rect in enumerate(layout.rects)
            if layout.columns[index] == 0
            and rect.bottom >= maximum_scroll
            and rect.y <= maximum_scroll + active_viewport.height
        ),
        key=lambda index: layout.rects[index].y,
    )
    dragged_id = values[bottom_left].id

    # Hold at the upper-left edge until auto-scroll reaches the first slot.
    first_session = drag_session(simulator, values, bottom_left, active_viewport)
    first_decision = drag_to_slot(simulator, first_session, active_viewport, 0)
    while first_decision.scroll_offset > 0:
        active_viewport.scroll_offset = first_decision.scroll_offset
        first_decision = simulator.advance_drag(first_session, active_viewport, 10, 5)
    assert first_decision.destination_index == 0
    first_projection = simulator.project_preview(
        first_session,
        first_decision,
        active_viewport,
        clip_columns=False,
    )
    first_visual = first_projection.item_for(dragged_id)
    assert first_visual is not None and first_visual.center_is_visible

    values_by_id = {item.id: item for item in values}
    values = [
        values_by_id[item_id]
        for item_id in first_decision.preview_layout.item_ids
    ]
    active_viewport.scroll_offset = 0
    second_session = drag_session(
        simulator,
        values,
        0,
        active_viewport,
        first_decision.preview_layout,
    )

    # Move diagonally through both middle columns before holding at the
    # lower-right edge. Every intermediate pointer position must keep the
    # dragged card visible while the surrounding cards reflow.
    previous_x = -1.0
    for pointer_x, pointer_y in ((120, 120), (230, 210), (340, 330)):
        decision = simulator.advance_drag(
            second_session,
            active_viewport,
            pointer_x,
            pointer_y,
        )
        projection = simulator.project_preview(
            second_session,
            decision,
            active_viewport,
            clip_columns=False,
        )
        visual = projection.item_for(dragged_id)
        assert visual is not None and visual.center_is_visible
        assert visual.visual_rect.x > previous_x
        previous_x = visual.visual_rect.x

    final_decision = decision
    while final_decision.scroll_offset < active_viewport.maximum_scroll:
        active_viewport.scroll_offset = final_decision.scroll_offset
        final_decision = simulator.advance_drag(
            second_session,
            active_viewport,
            430,
            395,
        )
    final_decision = drag_to_lane(
        simulator,
        second_session,
        active_viewport,
        3,
        len(
            [
                column
                for column in second_session.original_layout.columns
                if column == 3
            ]
        ),
    )
    final_rect = final_decision.preview_layout.rect_for(dragged_id)
    assert final_rect is not None and final_rect.x == 330


# Viewport anchoring


def test_anchor_restoration_preserves_the_same_screen_pixel_after_reflow():
    simulator = MasonryDragSimulator([0, 110], vertical_gap=10)
    values = items([80, 220, 60, 180, 90, 130])
    original = simulator.layout(values)
    active_viewport = MasonryViewport(0, 50, 220, 220, 170, 500)
    anchor = simulator.capture_anchor(original, active_viewport, "0")
    moved = simulator.layout(simulator.moved_items(values, 5, 2))
    moved_viewport = MasonryViewport(0, 50, 220, 220, 170, 500)

    restored = simulator.restore_anchor(moved, moved_viewport, anchor)
    anchor_rect = moved.rect_for(anchor.item_id)

    assert anchor.item_id != ""
    assert anchor_rect is not None
    assert moved_viewport.screen_y + anchor_rect.y - restored == anchor.screen_y


def test_anchor_prefers_a_visible_card_start_over_a_clipped_tall_card():
    simulator = MasonryDragSimulator([0, 110], vertical_gap=10)
    layout = MasonryLayoutSnapshot(
        ["tall", "visible"],
        [
            NativeRect(0, 0, 100, 600),
            NativeRect(110, 230, 100, 80),
        ],
        [0, 1],
        600,
    )
    viewport = MasonryViewport(0, 40, 220, 200, 200, 400)

    anchor = simulator.capture_anchor(layout, viewport)

    assert anchor.item_id == "visible"
    assert anchor.screen_y == 70


def test_anchor_clamps_a_sole_clipped_card_to_the_viewport_start():
    simulator = MasonryDragSimulator([0])
    layout = MasonryLayoutSnapshot(
        ["tall"],
        [NativeRect(0, 0, 100, 600)],
        [0],
        600,
    )
    viewport = MasonryViewport(0, 40, 100, 200, 200, 400)

    anchor = simulator.capture_anchor(layout, viewport)

    assert anchor.item_id == "tall"
    assert anchor.screen_y == viewport.screen_y


def test_anchor_restoration_clamps_when_reflow_shortens_the_content():
    simulator = MasonryDragSimulator([0])
    values = items([100, 100, 100])
    original = simulator.layout(values)
    active_viewport = MasonryViewport(0, 0, 100, 100, 200, 200)
    anchor = simulator.capture_anchor(original, active_viewport)
    short_viewport = MasonryViewport(0, 0, 100, 500, 200, 0)

    assert simulator.restore_anchor(original, short_viewport, anchor) == 0


def test_representative_drop_previews_preserve_geometry_invariants():
    patterns = (
        [20, 20, 20, 20, 20, 20],
        [20, 400, 21, 399, 22, 398],
        [900, 30, 40, 50, 60, 70],
    )
    for column_count in range(1, 5):
        simulator = MasonryDragSimulator(
            [float(index * 120) for index in range(column_count)],
            vertical_gap=7,
        )
        for pattern in patterns:
            values = items(pattern)
            original = simulator.layout(values)
            for source in (0, len(values) // 2, len(values) - 1):
                source_column = original.columns[source]
                for slot in simulator.drop_slots(values, source, original):
                    layout = simulator.layout_for_slot(
                        values,
                        source,
                        slot,
                        original,
                    )
                    assert sorted(layout.item_ids) == sorted(
                        item.id for item in values
                    )
                    source_layout_index = layout.index_of(values[source].id)
                    source_rect = layout.rects[source_layout_index]
                    assert slot.destination_index == source_layout_index
                    assert (
                        slot.source_rect.x,
                        slot.source_rect.y,
                        slot.source_rect.width,
                        slot.source_rect.height,
                    ) == (
                        source_rect.x,
                        source_rect.y,
                        source_rect.width,
                        source_rect.height,
                    )
                    assert layout.columns[source_layout_index] == (
                        slot.destination_column
                    )
                    values_by_id = {item.id: item for item in values}
                    committed = simulator.layout_in_columns(
                        [values_by_id[item_id] for item_id in layout.item_ids],
                        layout.columns,
                    )
                    assert [
                        (rect.x, rect.y, rect.width, rect.height)
                        for rect in committed.rects
                    ] == [
                        (rect.x, rect.y, rect.width, rect.height)
                        for rect in layout.rects
                    ]
                    for item_id in original.item_ids:
                        original_index = original.index_of(item_id)
                        if (
                            item_id != values[source].id
                            and original.columns[original_index]
                            not in (source_column, slot.destination_column)
                        ):
                            before = original.rect_for(item_id)
                            after = layout.rect_for(item_id)
                            assert before is not None and after is not None
                            assert (after.x, after.y) == (before.x, before.y)
                    for left in range(len(layout.rects)):
                        for right in range(left + 1, len(layout.rects)):
                            if layout.columns[left] == layout.columns[right]:
                                first = layout.rects[left]
                                second = layout.rects[right]
                                assert (
                                    first.bottom + 7 <= second.y
                                    or second.bottom + 7 <= first.y
                                )


# Resilience at API boundaries


def test_empty_layout_and_invalid_sources_return_safe_results():
    simulator = MasonryDragSimulator([])
    active_viewport = viewport()

    assert simulator.layout([]).item_ids == []
    assert simulator.drop_slots([], 0) == []
    assert simulator.begin_drag([], 0, active_viewport, 0, 0) is None


def test_invalid_moves_preserve_items_and_out_of_range_destinations_are_clamped():
    simulator = MasonryDragSimulator([0])
    values = items([40, 50, 60])

    assert simulator.moved_items(values, -1, 1) == values
    assert simulator.moved_items(values, 99, 1) == values
    assert [item.id for item in simulator.moved_items(values, 1, -99)] == [
        "1",
        "0",
        "2",
    ]
    assert [item.id for item in simulator.moved_items(values, 1, 99)] == [
        "0",
        "2",
        "1",
    ]


def test_rectangles_and_scroll_bounds_tolerate_negative_native_measurements():
    rect = NativeRect(10, 20, -30, -40)
    simulator = MasonryDragSimulator([0])
    active_viewport = MasonryViewport(0, 0, -100, -200, -50, -10)

    assert (rect.width, rect.height, rect.right, rect.bottom) == (0, 0, 10, 20)
    assert simulator.edge_scroll_offset(active_viewport, 0) == 0


def test_empty_rectangle_intersections_are_canonical():
    viewport = NativeRect(0, 0, 200, 300)
    empty = [
        NativeRect(9, 400, 100, 20).intersection(viewport),
        NativeRect(300, 9, 100, 20).intersection(viewport),
        NativeRect(200, 100, 20, 20).intersection(viewport),
    ]
    overlap = NativeRect(150, 250, 100, 100).intersection(viewport)

    assert [
        (rect.x, rect.y, rect.width, rect.height) for rect in empty
    ] == 3 * [(0, 0, 0, 0)]
    assert (
        overlap.x,
        overlap.y,
        overlap.width,
        overlap.height,
    ) == (150, 250, 50, 50)
