from pyjs import js
from pyjs.web.domx import button, div, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class MessageScroller(Widget):
    def __init__(self, *children, label: str = "Messages"):
        super().__init__()
        self.content = div(
            tw("grid gap-4 p-4"),
            {"data-slot": "message-scroller-content"},
            *children,
        )
        self.viewport = div(
            tw("max-h-96 overflow-y-auto"),
            {
                "aria-label": label,
                "data-slot": "message-scroller-viewport",
                "role": "log",
            },
            self.content,
        )
        self.scroll_button = button(
            tw(
                "absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border bg-white "
                "px-3 py-1 text-xs shadow-sm"
            ),
            {"data-slot": "message-scroller-button", "type": "button"},
            "Jump to latest",
        )
        self.add(
            tw("relative"),
            {"data-slot": "message-scroller"},
            self.viewport,
            self.scroll_button,
        )
        self.scroll_button.addEventListener("click", self.jump_clicked)

    def scroll_to_latest(self):
        self.viewport.scrollTop = self.viewport.scrollHeight

    def jump_clicked(self, event: Event):
        self.scroll_to_latest()
