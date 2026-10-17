from pyjs import js
from pyjs.web.dom import DOMRect, Element, document
from pyjs.web.domx import tw
from pyjs.web.ui import Widget


@js
class FloatingPosition:
    def __init__(self, left: int, top: int):
        self.left = left
        self.top = top


@js
def calculate_floating_position(
    anchor: DOMRect,
    panel: DOMRect,
    side: str = "bottom",
    align: str = "start",
    side_offset: int = 4,
    align_offset: int = 0,
) -> FloatingPosition:
    horizontal = round(anchor.left) + align_offset
    vertical = round(anchor.top) + align_offset
    if align == "center":
        horizontal = round(anchor.left + (anchor.width - panel.width) / 2) + align_offset
        vertical = round(anchor.top + (anchor.height - panel.height) / 2) + align_offset
    elif align == "end":
        horizontal = round(anchor.right - panel.width) + align_offset
        vertical = round(anchor.bottom - panel.height) + align_offset

    if side == "top":
        return FloatingPosition(
            horizontal, round(anchor.top - panel.height) - side_offset
        )
    if side == "right":
        return FloatingPosition(round(anchor.right) + side_offset, vertical)
    if side == "left":
        return FloatingPosition(round(anchor.left - panel.width) - side_offset, vertical)
    return FloatingPosition(horizontal, round(anchor.bottom) + side_offset)


@js
class FloatingPanel(Widget):
    def __init__(self, *children):
        super().__init__()
        self.add(
            tw("fixed z-50"),
            {
                "data-state": "closed",
                "style": (
                    "position: fixed; left: 0px; top: 0px; z-index: 50; "
                    "display: none; visibility: hidden"
                ),
            },
            *children,
        )

    def open(
        self,
        anchor: Element,
        side: str = "bottom",
        align: str = "start",
        side_offset: int = 4,
        align_offset: int = 0,
    ) -> FloatingPosition:
        document.body.append(self)
        self.style.display = "block"
        self.style.visibility = "hidden"
        position = calculate_floating_position(
            anchor.getBoundingClientRect(),
            self.getBoundingClientRect(),
            side,
            align,
            side_offset,
            align_offset,
        )
        self.style.left = str(position.left) + "px"
        self.style.top = str(position.top) + "px"
        self.style.visibility = "visible"
        self.setAttribute("data-side", side)
        self.setAttribute("data-align", align)
        self.setAttribute("data-state", "open")
        return position

    def close(self):
        self.style.display = "none"
        self.setAttribute("data-state", "closed")
        self.remove()
