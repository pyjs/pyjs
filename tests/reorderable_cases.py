from pyjs import js
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderItem,
    ReorderRow,
    ReorderSession,
    edge_scroll_offset,
)


@js
def assert_hierarchical_reorder_scenarios():
    engine = HierarchicalReorder(max_depth=3, indent_step=36)

    parent_drag = engine.begin(
        [
            ReorderItem("parent", 0),
            ReorderItem("child", 1),
            ReorderItem("grandchild", 2),
            ReorderItem("other", 0),
        ],
        0,
    )
    assert isinstance(parent_drag, ReorderSession)
    parent_preview = parent_drag.preview(1, 0)
    assert parent_preview.hidden_item_ids == ["child", "grandchild"]
    assert parent_preview.visible_item_ids() == ["other", "parent"]
    assert parent_preview.committed_item_ids() == [
        "other",
        "parent",
        "child",
        "grandchild",
    ]
    assert parent_preview.committed_depths() == [0, 0, 1, 2]

    adopt_siblings = engine.begin(
        [
            ReorderItem("parent", 0),
            ReorderItem("first", 1),
            ReorderItem("second", 1),
            ReorderItem("second-child", 2),
            ReorderItem("third", 1),
            ReorderItem("next-root", 0),
        ],
        1,
    )
    assert isinstance(adopt_siblings, ReorderSession)
    adopted = adopt_siblings.preview(1, 0)
    assert adopted.committed_item_ids() == [
        "parent",
        "first",
        "second",
        "second-child",
        "third",
        "next-root",
    ]
    assert adopted.committed_depths() == [0, 0, 1, 2, 1, 0]

    deep_adoption = engine.begin(
        [
            ReorderItem("root", 0),
            ReorderItem("parent", 1),
            ReorderItem("first", 2),
            ReorderItem("second", 2),
            ReorderItem("leaf", 3),
            ReorderItem("after-parent", 1),
        ],
        2,
    )
    assert isinstance(deep_adoption, ReorderSession)
    deeply_adopted = deep_adoption.preview(2, 0)
    assert deeply_adopted.committed_depths() == [0, 1, 0, 1, 2, 1]

    variable_rows = [
        ReorderRow("short", 0, 40),
        ReorderRow("tall", 40, 160),
        ReorderRow("last", 200, 64),
    ]
    single = engine.begin(
        [
            ReorderItem("source", 0),
            ReorderItem("short", 0),
            ReorderItem("tall", 0),
            ReorderItem("last", 0),
        ],
        0,
    )
    assert isinstance(single, ReorderSession)
    assert single.insertion_index_at(variable_rows, 19) == 0
    assert single.insertion_index_at(variable_rows, 21) == 1
    assert single.insertion_index_at(variable_rows, 119) == 1
    assert single.insertion_index_at(variable_rows, 121) == 2
    assert single.insertion_index_at(variable_rows, 400) == 3

    depth_limited = engine.begin(
        [
            ReorderItem("root", 0),
            ReorderItem("source", 1),
            ReorderItem("child", 2),
            ReorderItem("leaf", 3),
            ReorderItem("target", 2),
        ],
        1,
    )
    assert isinstance(depth_limited, ReorderSession)
    limited = depth_limited.preview(2, 99)
    assert limited.target_depth == 1
    assert limited.committed_depths() == [0, 1, 2, 3, 2]

    three_levels = HierarchicalReorder(max_depth=2)
    session = three_levels.begin(
        [ReorderItem("root", 0), ReorderItem("child", 1)],
        1,
    )
    assert isinstance(session, ReorderSession)
    assert session.depth_for_delta(35) == 1
    assert session.depth_for_delta(36) == 2
    assert session.depth_for_delta(-36) == 0
    assert session.preview(1, 10).target_depth == 1

    open_depth = HierarchicalReorder()
    session = open_depth.begin(
        [
            ReorderItem("source", 0),
            ReorderItem("root", 0),
            ReorderItem("one", 1),
            ReorderItem("two", 2),
            ReorderItem("three", 3),
            ReorderItem("four", 4),
        ],
        0,
    )
    assert isinstance(session, ReorderSession)
    deepest = session.preview(5, 99)
    assert deepest.target_depth == 5
    assert deepest.committed_depths() == [0, 1, 2, 3, 4, 5]

    assert engine.begin([], 0) is None
    assert engine.begin([ReorderItem("only", 0)], -1) is None

    assert edge_scroll_offset(100, 100, 400, 80, 300) == 56
    assert edge_scroll_offset(150, 100, 400, 80, 300) == 74.75
    assert edge_scroll_offset(450, 100, 400, 80, 300) == 85.25
    assert edge_scroll_offset(500, 100, 400, 80, 300) == 104
    assert edge_scroll_offset(300, 100, 400, 80, 300) == 80
    assert edge_scroll_offset(100, 100, 400, 0, 300) == 0
    assert edge_scroll_offset(500, 100, 400, 300, 300) == 300
