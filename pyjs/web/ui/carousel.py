from pyjs import js
from pyjs.web.domx import ProxyElement, button, div, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class CarouselItem(ProxyElement):
    def __init__(self, *children):
        self.element = div(
            tw("min-w-0 flex-none basis-full"),
            {
                "aria-hidden": "true",
                "data-slot": "carousel-item",
                "role": "group",
                "style": "display: none",
            },
            *children,
        )

    def set_active(self, active: bool):
        self.element.setAttribute("aria-hidden", "false" if active else "true")
        self.element.setAttribute("data-active", "true" if active else "false")
        self.element.setAttribute(
            "style", "display: block" if active else "display: none"
        )


@js
class Carousel(Widget):
    def __init__(self, *items: CarouselItem, label: str = "Carousel", loop: bool = False):
        super().__init__()
        self.items: list[CarouselItem] = []
        for item in items:
            self.items.append(item)
        self.index = 0
        self.loop = loop
        self.previous_button = button(
            tw(
                "absolute left-2 top-1/2 z-10 size-9 -translate-y-1/2 rounded-full border bg-white"
            ),
            {
                "aria-label": "Previous slide",
                "data-slot": "carousel-previous",
                "type": "button",
            },
            "‹",
        )
        self.next_button = button(
            tw(
                "absolute right-2 top-1/2 z-10 size-9 -translate-y-1/2 rounded-full border bg-white"
            ),
            {"aria-label": "Next slide", "data-slot": "carousel-next", "type": "button"},
            "›",
        )
        self.add(
            tw("relative w-full overflow-hidden"),
            {
                "aria-label": label,
                "aria-roledescription": "carousel",
                "data-slot": "carousel",
            },
            div(tw("overflow-hidden"), {"data-slot": "carousel-content"}, *items),
            self.previous_button,
            self.next_button,
        )
        self.previous_button.addEventListener("click", self.previous)
        self.next_button.addEventListener("click", self.next)
        self.show(0)

    def show(self, index: int):
        if len(self.items) == 0:
            return
        if self.loop:
            index += len(self.items)
            index %= len(self.items)
        elif index < 0:
            index = 0
        elif index >= len(self.items):
            index = len(self.items) - 1
        self.index = index
        for item_index in range(len(self.items)):
            self.items[item_index].set_active(item_index == index)
        self.setAttribute("data-index", str(index))
        if not self.loop:
            if index == 0:
                self.previous_button.setAttribute("disabled", "")
            else:
                self.previous_button.removeAttribute("disabled")
            if index == len(self.items) - 1:
                self.next_button.setAttribute("disabled", "")
            else:
                self.next_button.removeAttribute("disabled")

    def previous(self, event: Event):
        self.show(self.index - 1)

    def next(self, event: Event):
        self.show(self.index + 1)
