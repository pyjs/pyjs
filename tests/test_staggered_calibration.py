import pytest

from pyjs.ui.masonry import MasonryDragSimulator, MasonryItemGeometry
from tests.staggered_calibration_cases import heights, outer_tops, spans


@pytest.mark.parametrize("columns", [2, 3, 4])
def test_initial_layout_matches_native_margin_and_full_span_contract(columns):
    sizes = heights()
    expected_tops = outer_tops(columns)
    expected_spans = spans(columns)
    width = 601 // columns
    top = 0
    for header, end in [(0, 4), (4, 8)]:
        assert top == expected_tops[header]
        top += sizes[header]
        items = [MasonryItemGeometry(
            str(index), width - 10, sizes[index], placement_height=sizes[index] + 14,
            margin_left=3, margin_right=7, margin_top=5, margin_bottom=9,
        ) for index in range(header + 1, end)]
        model = MasonryDragSimulator([column * width for column in range(columns)], top)
        layout = model.layout(items)
        for item_id, rect, span in zip(layout.item_ids, layout.rects, layout.columns, strict=True):
            index = int(item_id)
            assert span == expected_spans[index]
            assert rect.x == span * width + 3
            assert rect.y == expected_tops[index] + 5
            assert rect.height == sizes[index]
        top = max(rect.bottom + 9 for rect in layout.rects)
