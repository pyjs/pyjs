from pyjs import js
from pyjs.web.domx import button, div, ref, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
def MessageScrollerViewport(*children, label: str = "Messages"):
    return div(
        tw(
            "size-full min-h-0 min-w-0 overflow-y-auto overscroll-contain "
            "[scrollbar-gutter:stable]"
        ),
        {
            "aria-label": label,
            "data-slot": "message-scroller-viewport",
            "role": "log",
        },
        *children,
    )


@js
def MessageScrollerContent(*children):
    return div(
        tw("flex h-max min-h-full flex-col gap-6 p-4"),
        {"data-slot": "message-scroller-content"},
        *children,
    )


@js
def MessageScrollerItem(*children, scroll_anchor: bool = False):
    return div(
        tw("min-w-0 shrink-0 [content-visibility:auto]"),
        {
            "data-scroll-anchor": "true" if scroll_anchor else "false",
            "data-slot": "message-scroller-item",
        },
        *children,
    )


@js
def MessageScrollerButton(
    *children,
    direction: str = "end",
    label: str = "Scroll to latest message",
):
    return button(
        tw(
            "absolute left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-2 "
            "rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium "
            "text-slate-700 shadow-lg transition-all hover:bg-slate-50 focus-visible:ring-2 "
            "focus-visible:ring-violet-300 data-[active=false]:pointer-events-none "
            "data-[active=false]:scale-95 data-[active=false]:opacity-0 "
            "data-[active=true]:scale-100 data-[active=true]:opacity-100 "
            "data-[direction=end]:bottom-4 data-[direction=start]:top-4"
        ),
        {
            "aria-label": label,
            "data-active": "false",
            "data-direction": direction,
            "data-slot": "message-scroller-button",
            "tabindex": "-1",
            "type": "button",
        },
        *children,
    )


@js
class MessageScroller(Widget):
    def __init__(self, *children, label: str = "Messages"):
        super().__init__()
        self.content = ref(MessageScrollerContent(*children))
        self.viewport = ref(MessageScrollerViewport(self.content, label=label))
        self.scroll_button = ref(MessageScrollerButton("↓ Latest"))
        self.add(
            tw("relative flex size-full min-h-0 flex-col overflow-hidden"),
            {"data-slot": "message-scroller"},
            self.viewport,
            self.scroll_button,
        )
        self.viewport.addEventListener("scroll", self.scrolled)
        self.scroll_button.addEventListener("click", self.jump_clicked)

    def initialize(self):
        self.update_scroll_button()

    def is_at_latest(self) -> bool:
        remaining = (
            self.viewport.scrollHeight
            - self.viewport.scrollTop
            - self.viewport.clientHeight
        )
        return remaining <= 24

    def scroll_to_latest(self):
        self.viewport.scrollTop = self.viewport.scrollHeight
        self.update_scroll_button()

    def scroll_to_start(self):
        self.viewport.scrollTop = 0
        self.update_scroll_button()

    def replace_messages(self, *children):
        follow_latest = self.is_at_latest()
        self.content.replaceChildren(*children)
        if follow_latest:
            self.scroll_to_latest()
        else:
            self.update_scroll_button()

    def update_scroll_button(self):
        active = not self.is_at_latest()
        self.scroll_button.setAttribute("data-active", "true" if active else "false")
        self.scroll_button.setAttribute("aria-hidden", "false" if active else "true")
        if active:
            self.scroll_button.removeAttribute("tabindex")
        else:
            self.scroll_button.setAttribute("tabindex", "-1")

    def scrolled(self, event: Event):
        self.update_scroll_button()

    def jump_clicked(self, event: Event):
        self.scroll_to_latest()
