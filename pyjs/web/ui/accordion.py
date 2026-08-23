from typing import cast

from pyjs import js
from pyjs.web.dom import Element, HTMLCollection
from pyjs.web.domx import ref, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.ui import Widget


@js
def validate_accordion_value(value: str, values: list[str]):
    for existing in values:
        if existing == value:
            raise ValueError(
                "AccordionItem values must be unique within an AccordionGroup"
            )
    values.append(value)


@js
class AccordionItem(Widget):
    def __init__(self, value: str, title: str, *children, open: bool = False):
        super().__init__()
        self.icon = ref(
            tag(
                "span",
                tw("pointer-events-none text-slate-500 transition-transform"),
                {"aria-hidden": "true", "data-slot": "accordion-trigger-icon"},
                "⌄",
            )
        )
        self.trigger = ref(
            tag(
                "button",
                tw(
                    "flex w-full items-center justify-between gap-4 py-4 text-left text-sm "
                    "font-medium text-slate-950 hover:underline focus-visible:outline-none "
                    "focus-visible:ring-2 focus-visible:ring-slate-400"
                ),
                {"data-slot": "accordion-trigger", "type": "button"},
                title,
                self.icon,
            )
        )
        self.content = ref(
            tag(
                "div",
                tw("overflow-hidden pb-4 text-sm leading-6 text-slate-600"),
                {"data-slot": "accordion-content"},
                *children,
            )
        )
        self.link_controls()
        self.add(
            tw("border-b border-slate-200 last:border-b-0"),
            {"data-slot": "accordion-item", "data-value": value},
            tag("h3", tw("flex"), self.trigger),
            self.content,
        )
        self.set_open(open)

    def link_controls(self):
        item_id = self.get_component_id()
        trigger_id = item_id + "-trigger"
        content_id = item_id + "-content"
        self.trigger.setAttribute("id", trigger_id)
        self.trigger.setAttribute("aria-controls", content_id)
        self.content.setAttribute("id", content_id)
        self.content.setAttribute("aria-labelledby", trigger_id)
        self.content.setAttribute("role", "region")

    def get_value(self) -> str:
        value = self.getAttribute("data-value")
        if value is None:
            return ""
        return value

    def is_open(self) -> bool:
        return self.getAttribute("data-state") == "open"

    def set_open(self, open: bool):
        self.setAttribute("data-state", "open" if open else "closed")
        self.trigger.setAttribute("aria-expanded", "true" if open else "false")
        self.trigger.setAttribute("data-state", "open" if open else "closed")
        self.content.setAttribute("data-state", "open" if open else "closed")
        self.content.setAttribute("style", "display: block" if open else "display: none")
        self.icon.setAttribute("style", "transform: rotate(180deg)" if open else "")


@js
class AccordionGroup(Widget):
    def __init__(self, *items: AccordionItem, multiple: bool = False):
        super().__init__()
        values: list[str] = []
        for item in items:
            validate_accordion_value(item.get_value(), values)
        self.add(
            tw("block w-full"),
            {"data-slot": "accordion", "multiple": "true" if multiple else "false"},
            *items,
        )
        self.addEventListener("click", self.clicked)
        self.addEventListener("keydown", self.keydown)

    def get_items(self) -> HTMLCollection[AccordionItem]:
        return cast(HTMLCollection[AccordionItem], self.children)

    def allows_multiple(self) -> bool:
        return self.getAttribute("multiple") == "true"

    def set_open(self, value: str, open: bool):
        close_others = open and not self.allows_multiple()
        for item in self.get_items():
            item_value = item.get_value()
            if item_value == value:
                item.set_open(open)
            elif close_others:
                item.set_open(False)

    def clicked(self, event: Event):
        target = cast(Element, event.target)
        for item in self.get_items():
            if item.trigger.contains(target):
                self.set_open(item.get_value(), not item.is_open())
                return

    def keydown(self, event: KeyboardEvent):
        if (
            event.key != "ArrowUp"
            and event.key != "ArrowDown"
            and event.key != "Home"
            and event.key != "End"
        ):
            return
        target = cast(Element, event.target)
        first_item: AccordionItem | None = None
        last_item: AccordionItem | None = None
        previous_item: AccordionItem | None = None
        following_item: AccordionItem | None = None
        found_current = False
        for item in self.get_items():
            if first_item is None:
                first_item = item
            if item.trigger.contains(target):
                found_current = True
                previous_item = last_item
            elif found_current and following_item is None:
                following_item = item
            last_item = item
        if not found_current:
            return
        next_item: AccordionItem | None = None
        if event.key == "Home":
            next_item = first_item
        elif event.key == "End":
            next_item = last_item
        elif event.key == "ArrowUp":
            next_item = previous_item
            if next_item is None:
                next_item = last_item
        else:
            next_item = following_item
            if next_item is None:
                next_item = first_item
        event.preventDefault()
        if next_item is not None:
            next_item.trigger.focus()
