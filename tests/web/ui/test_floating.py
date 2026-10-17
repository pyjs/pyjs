import pytest

from pyjs.web.dom import DOMRect
from pyjs.web.ui.floating import calculate_floating_position


def rect(left: float, top: float, width: float, height: float) -> DOMRect:
    value = DOMRect()
    value.left = left
    value.top = top
    value.right = left + width
    value.bottom = top + height
    value.width = width
    value.height = height
    return value


@pytest.mark.pyjs_python
def test_floating_position_supports_shadcn_sides_alignment_and_offsets():
    anchor = rect(100, 100, 40, 20)
    panel = rect(0, 0, 80, 60)

    bottom = calculate_floating_position(anchor, panel)
    assert (bottom.left, bottom.top) == (100, 124)

    top = calculate_floating_position(anchor, panel, "top", "center", 4, 2)
    assert (top.left, top.top) == (82, 36)

    left = calculate_floating_position(anchor, panel, "left", "end", 4, 3)
    assert (left.left, left.top) == (16, 63)

    right = calculate_floating_position(anchor, panel, "right", "center", 4, -2)
    assert (right.left, right.top) == (144, 78)
