from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, button, div, ref, tw
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
        self.items: list[Element] = []
        for item in items:
            self.items.append(item.element)
        self.index = 0
        self.loop = loop
        self.setAttribute("data-loop", "true" if loop else "false")
        self.previous_button = ref(button(
            tw(
                "absolute left-2 top-1/2 z-10 size-9 -translate-y-1/2 rounded-full border bg-white"
            ),
            {
                "aria-label": "Previous slide",
                "data-slot": "carousel-previous",
                "type": "button",
            },
            "‹",
        ))
        self.next_button = ref(button(
            tw(
                "absolute right-2 top-1/2 z-10 size-9 -translate-y-1/2 rounded-full border bg-white"
            ),
            {"aria-label": "Next slide", "data-slot": "carousel-next", "type": "button"},
            "›",
        ))
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
        self.show(0)

    def initialize(self):
        self.items = []
        for item in self.querySelectorAll("[data-slot=carousel-item]"):
            self.items.append(item)
        index = self.getAttribute("data-index")
        self.index = 0 if index is None else int(index)
        self.loop = self.getAttribute("data-loop") == "true"
        self.previous_button.addEventListener("click", self.previous)
        self.next_button.addEventListener("click", self.next)

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
            item = self.items[item_index]
            active = item_index == index
            item.setAttribute("aria-hidden", "false" if active else "true")
            item.setAttribute("data-active", "true" if active else "false")
            item.setAttribute("style", "display: block" if active else "display: none")
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
