from typing import Final

from pyjs import JS, js
from pyjs.web.domx import div, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget
from pyjs.web.ui.effects import EFFECTS_CSS, sync_scroll_fade

SCROLLBAR_CSS: Final[JS] = (
    "[data-slot='scroll-area'],"
    "[data-slot='message-scroller-viewport']{"
    "scrollbar-width:thin;"
    "scrollbar-color:var(--pyjs-border,#4e4e4e) var(--pyjs-surface,#252526);}"
    "[data-slot='scroll-area']::-webkit-scrollbar,"
    "[data-slot='message-scroller-viewport']::-webkit-scrollbar{"
    "width:10px;height:10px;}"
    "[data-slot='scroll-area']::-webkit-scrollbar-track,"
    "[data-slot='message-scroller-viewport']::-webkit-scrollbar-track{"
    "background:var(--pyjs-surface,#252526);}"
    "[data-slot='scroll-area']::-webkit-scrollbar-thumb,"
    "[data-slot='message-scroller-viewport']::-webkit-scrollbar-thumb{"
    "background:var(--pyjs-border,#4e4e4e);border-radius:6px;"
    "border:2px solid var(--pyjs-surface,#252526);}"
    "[data-slot='scroll-area']::-webkit-scrollbar-thumb:hover,"
    "[data-slot='message-scroller-viewport']::-webkit-scrollbar-thumb:hover{"
    "background:var(--pyjs-muted-foreground,#6a6a6a);}"
    "[data-slot='scroll-area']::-webkit-scrollbar-corner,"
    "[data-slot='message-scroller-viewport']::-webkit-scrollbar-corner{"
    "background:var(--pyjs-surface,#252526);}"
)


@js
class ScrollArea(Widget):
    def __init__(self, *children, height: str = "12rem"):
        super().__init__()
        self.add(
            tw(
                "relative overflow-auto rounded-md focus-visible:outline-none "
                "focus-visible:ring-2"
            ),
            {
                "data-scroll-fade": "y",
                "data-slot": "scroll-area",
                "style": "max-height: " + height,
                "tabindex": "0",
            },
            tag("style", SCROLLBAR_CSS + EFFECTS_CSS),
            *children,
        )

    def initialize(self):
        self.addEventListener("scroll", self.scrolled)
        sync_scroll_fade(self)

    def scrolled(self, event: Event) -> None:
        sync_scroll_fade(self)


@js
def ScrollBar(orientation: str = "vertical"):
    return div(
        tw("pointer-events-none absolute opacity-0"),
        {
            "aria-hidden": "true",
            "data-orientation": orientation,
            "data-slot": "scroll-bar",
        },
    )
