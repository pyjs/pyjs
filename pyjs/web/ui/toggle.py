from typing import cast

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, button, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class Toggle(ProxyElement):
    def __init__(
        self,
        *children: object,
        value: str | None = None,
        pressed: bool = False,
        variant: str = "default",
        size: str = "default",
    ):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md px-3 text-sm font-medium "
                "text-slate-700 outline-none transition-colors hover:bg-slate-100 "
                "focus-visible:ring-2 focus-visible:ring-slate-400 disabled:opacity-50 "
                "data-[state=on]:bg-slate-200 data-[state=on]:text-slate-950 "
                "data-[variant=outline]:border data-[variant=outline]:border-slate-300 "
                "data-[variant=outline]:bg-white data-[size=sm]:h-8 data-[size=sm]:px-2.5 "
                "data-[size=lg]:h-10 data-[size=lg]:px-4"
            ),
            {
                "data-size": size,
                "data-slot": "toggle",
                "data-variant": variant,
                "type": "button",
            },
            *children,
        )
        if value is not None:
            self.element.setAttribute("data-value", value)
        self.set_pressed(pressed)
        self.element.addEventListener("click", self.clicked)

    def is_pressed(self) -> bool:
        return self.element.getAttribute("aria-pressed") == "true"

    def set_pressed(self, pressed: bool):
        self.element.setAttribute("aria-pressed", "true" if pressed else "false")
        self.element.setAttribute("data-state", "on" if pressed else "off")

    def clicked(self, event: Event):
        self.set_pressed(not self.is_pressed())


@js
class ToggleGroup(Widget):
    def __init__(
        self,
        *items: Toggle,
        multiple: bool = False,
        orientation: str = "horizontal",
    ):
        super().__init__()
        current_value = ""
        for item in items:
            value = item.getAttribute("data-value")
            if value is None:
                raise ValueError("ToggleGroup items must define a value")
            if item.is_pressed():
                current_value = value
        self.add(
            tw(
                "flex w-fit items-center gap-1 data-[orientation=vertical]:flex-col "
                "data-[orientation=vertical]:items-stretch"
            ),
            {
                "data-multiple": "true" if multiple else "false",
                "data-orientation": orientation,
                "data-slot": "toggle-group",
                "data-value": current_value,
                "role": "group",
            },
            *items,
        )
        self.addEventListener("click", self.clicked)

    def allows_multiple(self) -> bool:
        return self.getAttribute("data-multiple") == "true"

    def current_value(self) -> str:
        value = self.getAttribute("data-value")
        if value is None:
            return ""
        return value

    def clicked(self, event: Event):
        target = cast(Element, event.target)
        selected = target.closest("[data-slot=toggle]")
        if selected is None or self.allows_multiple():
            return
        if selected.getAttribute("aria-pressed") != "true":
            self.setAttribute("data-value", "")
            return
        value = selected.getAttribute("data-value")
        if value is not None:
            self.setAttribute("data-value", value)
        items = self.querySelectorAll("[data-slot=toggle]")
        for item in items:
            if item is not selected:
                item.setAttribute("aria-pressed", "false")
                item.setAttribute("data-state", "off")
