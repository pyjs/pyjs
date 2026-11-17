"""Ordered item navigation shared by searchable controls and custom widgets."""

from pyjs import js
from pyjs.web.html import HTMLElement


@js
class ListNavigation:
    """Own highlighting without deciding how a widget selects or activates items."""

    def __init__(self, items: list[HTMLElement], attribute: str = "data-highlighted"):
        self.items = items
        self.attribute = attribute
        self.index = 0

    def available(self) -> list[HTMLElement]:
        return [item for item in self.items
                if not item.hasAttribute("hidden")
                and item.getAttribute("aria-disabled") != "true"]

    def current(self) -> HTMLElement | None:
        items = self.available()
        if self.index < 0 or self.index >= len(items):
            return None
        return items[self.index]

    def highlight(self, index: int) -> HTMLElement | None:
        for item in self.items:
            item.removeAttribute(self.attribute)
        items = self.available()
        if not items:
            self.index = 0
            return None
        self.index = index % len(items)
        item = items[self.index]
        item.setAttribute(self.attribute, "true")
        return item


@js
def filter_items(items: list[HTMLElement], query: str, attributes: list[str]) -> int:
    """Filter by joined attribute text; disabled matching rows remain visible."""
    query = query.lower()
    count = 0
    for item in items:
        text = " ".join(item.getAttribute(name) or "" for name in attributes)
        visible = query in text.lower()
        if visible:
            item.removeAttribute("hidden")
            count += 1
        else:
            item.setAttribute("hidden", "")
    return count
