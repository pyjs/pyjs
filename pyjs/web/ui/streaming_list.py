from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import button, div, ref, span, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget
from pyjs.web.ui.message_scroller import MessageScroller


@js
class StreamingList(Widget):
    """Bound a live list while preserving pause and follow-tail behavior.

    New values append at the bottom. Historical values prepend without moving
    the visible content. With ``newest_first=True``, live values prepend and
    history appends instead. If a paused queue overflows, ``dropped_count`` and
    the accessible status expose the loss until ``clear()`` or ``replace()``
    loads a new snapshot.

    Args:
        *children: Initially rendered rows in chronological order.
        label: Accessible label for the scrolling viewport.
        max_items: Maximum live rows retained in the DOM and pause queue.
    """

    def __init__(
        self,
        *children: Element,
        label: str = "Streaming activity",
        max_items: int = 500,
        newest_first: bool = False,
    ):
        super().__init__()
        if max_items < 1:
            raise ValueError("A streaming list must retain at least one item.")
        self.max_items = max_items
        self.newest_first = newest_first
        self.paused = False
        self.dropped_count = 0
        self._pending: list[Element] = []
        self.set_data("max-items", str(max_items))
        self.set_data("newest-first", "true" if newest_first else "false")
        self.status = ref(
            span(
                tw("text-xs text-slate-500"),
                {"aria-live": "polite", "data-slot": "streaming-list-status"},
                "Live",
            )
        )
        self.pause_button = ref(
            button(
                tw(
                    "rounded-md border border-slate-200 bg-white px-2.5 py-1.5 "
                    "text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 "
                    "focus-visible:ring-2 focus-visible:ring-violet-300"
                ),
                {
                    "aria-pressed": "false",
                    "data-slot": "streaming-list-pause",
                    "type": "button",
                },
                "Pause",
            )
        )
        self.scroller = ref(
            MessageScroller(
                *children,
                label=label,
                newest_first=newest_first,
            )
        )
        self.pause_button.addEventListener("click", self.toggle_paused)
        self.add(
            tw("flex min-h-0 flex-col"),
            {"data-paused": "false", "data-slot": "streaming-list"},
            div(
                tw("flex items-center justify-between gap-3 px-3 py-2"),
                self.status,
                self.pause_button,
            ),
            div(tw("min-h-0 flex-1"), self.scroller),
        )
        self._trim()

    def initialize(self):
        max_items = self.get_data("max-items")
        self.max_items = 500 if max_items is None else int(max_items)
        self.newest_first = self.get_data("newest-first") == "true"
        self.paused = False
        self.dropped_count = 0
        self._pending = []
        self._trim()
        self._update_status()

    def append_live(self, *children: Element):
        """Append live rows or queue them while the view is paused."""
        self._append_live_elements(*children)

    def _rows(self) -> list[Element]:
        rows: list[Element] = list(self.scroller.item_elements())
        return rows

    def _anchor_top(self, row: Element | None) -> float:
        if isinstance(row, HTMLElement):
            return row.getBoundingClientRect().top
        return 0.0

    def _restore_anchor(self, row: Element | None, previous_top: float) -> None:
        if not isinstance(row, HTMLElement) or not row.isConnected:
            return
        delta = row.getBoundingClientRect().top - previous_top
        if delta != 0:
            self.scroller.viewport.scrollTop = self.scroller.viewport.scrollTop + delta

    def _insert_before(self, child: Element, before: Element) -> None:
        self.scroller.content.insertBefore(child, before)

    def _prepend_children(self, before: Element, *children: Element) -> None:
        index = len(children) - 1
        first = before
        while index >= 0:
            self._insert_before(children[index], first)
            first = children[index]
            index = index - 1

    def _trim_overflow(self) -> None:
        rows = self._rows()
        while len(rows) > self.max_items:
            if self.newest_first:
                gone = rows.pop()
            else:
                gone = rows.pop(0)
            gone.remove()

    def _append_live_elements(self, *children: Element):
        if self.paused:
            for child in children:
                self._pending.append(child)
            while len(self._pending) > self.max_items:
                self._pending.pop(0)
                self.dropped_count += 1
            self._update_status()
            return
        follow_latest = self.scroller.is_at_latest()
        existing = self._rows()
        anchor: Element | None = None
        if not follow_latest and len(existing) > 0:
            if self.newest_first:
                anchor = existing[0]
            else:
                overflow = len(existing) + len(children) - self.max_items
                if overflow < 0:
                    overflow = 0
                if overflow < len(existing):
                    anchor = existing[overflow]
                else:
                    anchor = existing[len(existing) - 1]
        previous_top = self._anchor_top(anchor)
        spacer = self.scroller._ensure_spacer()
        if self.newest_first:
            first: Element = spacer
            if len(existing) > 0:
                first = existing[0]
            for child in children:
                self._insert_before(child, first)
                first = child
        else:
            for child in children:
                self._insert_before(child, spacer)
        self._trim_overflow()
        if follow_latest:
            self.scroller.scroll_to_latest()
        else:
            self._restore_anchor(anchor, previous_top)
            self.scroller.update_scroll_button()

    def add_history(self, *children: Element):
        """Add older rows without shifting the visible scroll position."""
        existing = self._rows()
        anchor: Element | None = None
        if len(existing) > 0:
            anchor = existing[0]
        previous_top = self._anchor_top(anchor)
        spacer = self.scroller._ensure_spacer()
        if self.newest_first:
            for child in children:
                self._insert_before(child, spacer)
        else:
            first: Element = spacer
            if len(existing) > 0:
                first = existing[0]
            self._prepend_children(first, *children)
        self._trim_overflow()
        if not self.newest_first:
            self._restore_anchor(anchor, previous_top)
        self.scroller.update_scroll_button()

    def set_paused(self, paused: bool):
        if self.paused == paused:
            return
        self.paused = paused
        self.setAttribute("data-paused", "true" if paused else "false")
        self.pause_button.setAttribute(
            "aria-pressed",
            "true" if paused else "false",
        )
        self.pause_button.textContent = "Resume" if paused else "Pause"
        if not paused and self._pending:
            pending = self._pending
            self._pending = []
            self._append_live_elements(*pending)
        self._update_status()

    def toggle_paused(self, event: Event):
        self.set_paused(not self.paused)

    def clear(self):
        self._pending.clear()
        self.dropped_count = 0
        self.scroller.content.replaceChildren()
        self.scroller._ensure_spacer()
        self.scroller.update_scroll_button()
        self._update_status()

    def replace(self, *children: Element):
        """Replace all rows, such as after a stream resynchronization."""
        self._pending.clear()
        self.dropped_count = 0
        self.scroller.content.replaceChildren(*children)
        self.scroller._ensure_spacer()
        self._trim()
        self.scroller.scroll_to_latest()
        self._update_status()

    def _trim(self):
        self._trim_overflow()

    def _update_status(self):
        if self.paused:
            pending = len(self._pending)
            if pending == 0:
                status = "Paused"
            else:
                status = str(pending) + " waiting"
        else:
            status = "Live"
        if self.dropped_count:
            status += ", " + str(self.dropped_count) + " dropped"
        self.status.textContent = status
