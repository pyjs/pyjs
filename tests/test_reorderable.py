import pytest

from pyjs.ui.reorderable import HierarchicalReorder, ReorderItem, project_reorder
from tests.reorderable_cases import assert_hierarchical_reorder_scenarios
from tests.reorderable_trace_cases import assert_reorder_trace_scenarios


def test_hierarchical_reorder_scenarios():
    assert_hierarchical_reorder_scenarios()


def test_reorder_trace_scenarios():
    assert_reorder_trace_scenarios()


@pytest.mark.parametrize("source,slot,depth", [
    (0, 0, 0), (0, 2, 2), (0, 99, 0), (1, 1, 0),
    (1, 0, 2), (2, 0, 0), (2, 3, 2), (3, 0, -1),
    (4, 0, 2), (4, 1, 2), (4, 2, 1), (4, -1, 0),
])
def test_platform_slots_match_pointer_session_projection(source, slot, depth):
    items = [ReorderItem(str(index), value) for index, value in enumerate([0, 1, 2, 1, 0])]
    session = HierarchicalReorder(2, 24).begin(items, source)
    assert session is not None
    expected = session.preview(slot, depth)
    actual = project_reorder(items, source, slot, depth, 2)
    assert actual is not None
    assert actual.source_id == expected.source_id
    assert actual.hidden_item_ids == expected.hidden_item_ids
    assert actual.insertion_index == expected.insertion_index
    assert actual.target_depth == expected.target_depth
    assert actual.visible_item_ids() == expected.visible_item_ids()
    assert actual.visible_depths() == expected.visible_depths()
    assert actual.committed_item_ids() == expected.committed_item_ids()
    assert actual.committed_depths() == expected.committed_depths()
    assert [item.depth for item in items] == [0, 1, 2, 1, 0]


@pytest.mark.parametrize("source", [-1, 0, 1])
def test_empty_projection_rejects_invalid_sources(source):
    assert project_reorder([], source, 0, 0, 2) is None
