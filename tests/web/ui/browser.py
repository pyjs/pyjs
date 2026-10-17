from typing import cast

from pyjs import js
from pyjs.testing.web import (
    bubbling_click,
    mount,
    press_key,
    selector_count,
)
from pyjs.web.dom import Element
from pyjs.web.domx import require_element
from pyjs.web.html import HTMLElement

__all__ = ["bubbling_click", "mount", "press_key", "require_element", "selector_count"]


@js
def place_element(element: Element, left: int, top: int, width: int = 120, height: int = 32):
    style = cast(HTMLElement, element).style
    style.position = "absolute"
    style.left = str(left) + "px"
    style.top = str(top) + "px"
    style.width = str(width) + "px"
    style.height = str(height) + "px"
    style.padding = "0px"
    style.margin = "0px"
    style.border = "0px"
    style.boxSizing = "border-box"


@js
def floating_side_gap(anchor: Element, panel: Element, side: str) -> int:
    anchor_bounds = anchor.getBoundingClientRect()
    panel_bounds = panel.getBoundingClientRect()
    if side == "top":
        return round(anchor_bounds.top) - round(panel_bounds.bottom)
    if side == "left":
        return round(anchor_bounds.left) - round(panel_bounds.right)
    if side == "right":
        return round(panel_bounds.left) - round(anchor_bounds.right)
    return round(panel_bounds.top) - round(anchor_bounds.bottom)


@js
def floating_alignment_gap(anchor: Element, panel: Element, side: str, align: str) -> int:
    anchor_bounds = anchor.getBoundingClientRect()
    panel_bounds = panel.getBoundingClientRect()
    if side == "top" or side == "bottom":
        if align == "start":
            return round(panel_bounds.left) - round(anchor_bounds.left)
        if align == "end":
            return round(panel_bounds.right) - round(anchor_bounds.right)
        return round(panel_bounds.left) - round(
            anchor_bounds.left + (anchor_bounds.width - panel_bounds.width) / 2
        )
    if align == "start":
        return round(panel_bounds.top) - round(anchor_bounds.top)
    if align == "end":
        return round(panel_bounds.bottom) - round(anchor_bounds.bottom)
    return round(panel_bounds.top) - round(
        anchor_bounds.top + (anchor_bounds.height - panel_bounds.height) / 2
    )
