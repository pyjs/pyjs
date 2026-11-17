import pytest

from pyjs.ui.floating import FloatingRect, place_floating


@pytest.mark.pyjs_python
def test_floating_position_supports_shadcn_sides_alignment_and_offsets():
    anchor = FloatingRect(100, 100, 40, 20)
    panel = FloatingRect(0, 0, 80, 60)

    bottom = place_floating(anchor, panel)
    assert (bottom.left, bottom.top) == (100, 124)

    top = place_floating(anchor, panel, side="top", align="center", align_offset=2)
    assert (top.left, top.top) == (82, 36)

    left = place_floating(anchor, panel, side="left", align="end", align_offset=3)
    assert (left.left, left.top) == (16, 63)

    right = place_floating(anchor, panel, side="right", align="center", align_offset=-2)
    assert (right.left, right.top) == (144, 78)


@pytest.mark.parametrize("side,anchor,expected", [
    ("bottom", (270, 170, 20, 20), (212, 106, "top")),
    ("top", (10, 10, 20, 20), (10, 34, "bottom")),
    ("right", (270, 100, 20, 20), (186, 100, "left")),
    ("left", (10, 100, 20, 20), (34, 100, "right")),
])
def test_floating_geometry_flips_and_clamps(side, anchor, expected):
    result = place_floating(FloatingRect(*anchor), FloatingRect(0, 0, 80, 60),
                            FloatingRect(0, 0, 300, 200), side=side)
    assert (result.left, result.top, result.side) == expected


def test_floating_geometry_constrains_large_content_and_respects_visual_viewport():
    result = place_floating(FloatingRect(250, 150, 20, 20),
                            FloatingRect(0, 0, 500, 600),
                            FloatingRect(100, 50, 200, 200))
    assert (result.left, result.top, result.side) == (108, 58, "top")
    assert (result.available_width, result.available_height) == (184, 88)


def test_floating_geometry_aligns_logical_edges_in_rtl():
    anchor = FloatingRect(100, 100, 40, 20)
    panel = FloatingRect(0, 0, 80, 60)
    start = place_floating(anchor, panel, rtl=True)
    end = place_floating(anchor, panel, align="end", rtl=True)
    assert start.left == 60
    assert end.left == 100
