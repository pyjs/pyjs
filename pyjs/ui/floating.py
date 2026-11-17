"""Popup geometry independent of DOM measurement and rendering."""

from pyjs import js


@js
class FloatingRect:
    def __init__(self, left: float, top: float, width: float, height: float):
        self.left = left
        self.top = top
        self.width = width
        self.height = height


@js
class FloatingPosition:
    def __init__(
        self, left: int, top: int, side: str,
        available_width: float, available_height: float,
    ):
        self.left = left
        self.top = top
        self.side = side
        self.available_width = available_width
        self.available_height = available_height


@js
def _clamp(value: float, lower: float, upper: float) -> float:
    # Scalar geometry needs neither iterable min/max nor rich comparisons.
    if value > upper:
        value = upper
    if value < lower:
        value = lower
    return value


@js
def place_floating(
    anchor: FloatingRect,
    panel: FloatingRect,
    viewport: FloatingRect | None = None,
    side: str = "bottom",
    align: str = "start",
    side_offset: int = 4,
    align_offset: int = 0,
    padding: int = 8,
    rtl: bool = False,
) -> FloatingPosition:
    """Flip toward more room, then constrain to the padded visible viewport."""
    vertical = side == "top" or side == "bottom"
    if not vertical and side != "left" and side != "right":
        raise ValueError("Floating side must be top, bottom, left or right")
    if align == "start":
        factor = 0.0
    elif align == "center":
        factor = 0.5
    elif align == "end":
        factor = 1.0
    else:
        raise ValueError("Floating alignment must be start, center or end")
    width = panel.width
    height = panel.height
    available_width = width
    available_height = height
    if viewport is not None:
        x = viewport.left + padding
        y = viewport.top + padding
        available_width = _clamp(viewport.width - 2 * padding, 0, viewport.width)
        available_height = _clamp(viewport.height - 2 * padding, 0, viewport.height)
        if vertical:
            before = anchor.top - y - side_offset
            after = y + available_height - anchor.top - anchor.height - side_offset
            needed = height
        else:
            before = anchor.left - x - side_offset
            after = x + available_width - anchor.left - anchor.width - side_offset
            needed = width
        preceding = side == "top" or side == "left"
        room = before if preceding else after
        opposite = after if preceding else before
        if needed > room and opposite > room:
            preceding = not preceding
            room = opposite
        if vertical:
            side = "top" if preceding else "bottom"
            available_height = _clamp(room, 0, available_height)
        else:
            side = "left" if preceding else "right"
            available_width = _clamp(room, 0, available_width)
        width = _clamp(width, 0, available_width)
        height = _clamp(height, 0, available_height)

    if vertical and rtl:
        factor = 1 - factor
    if vertical:
        left = anchor.left + (anchor.width - width) * factor + align_offset
        top = (anchor.top - height - side_offset if side == "top"
               else anchor.top + anchor.height + side_offset)
    else:
        left = (anchor.left - width - side_offset if side == "left"
                else anchor.left + anchor.width + side_offset)
        top = anchor.top + (anchor.height - height) * factor + align_offset
    if viewport is not None:
        left = _clamp(left, viewport.left + padding,
                      viewport.left + viewport.width - padding - width)
        top = _clamp(top, viewport.top + padding,
                     viewport.top + viewport.height - padding - height)
    return FloatingPosition(round(left), round(top), side,
                            available_width, available_height)
