from typing import cast

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget


@js
class Tab:
    def __init__(self, value: str, label: str, *children):
        self.value = value
        self.trigger = tag(
            "button",
            tw(
                "inline-flex h-8 flex-1 items-center justify-center rounded-md border "
                "border-transparent px-3 text-sm font-medium text-slate-500 transition-all "
                "hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 "
                "focus-visible:ring-slate-400 data-[state=active]:bg-white "
                "data-[state=active]:text-slate-950 data-[state=active]:shadow-sm"
            ),
            {
                "data-slot": "tabs-trigger",
                "data-value": value,
                "role": "tab",
                "type": "button",
            },
            label,
        )
        self.content = tag(
            "div",
            tw(
                "mt-3 rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-700"
            ),
            {"data-slot": "tabs-content", "data-value": value, "role": "tabpanel"},
            *children,
        )

    def link(self, id_prefix: str):
        trigger_id = id_prefix + "-trigger"
        content_id = id_prefix + "-content"
        self.trigger.setAttribute("id", trigger_id)
        self.trigger.setAttribute("aria-controls", content_id)
        self.content.setAttribute("id", content_id)
        self.content.setAttribute("aria-labelledby", trigger_id)

    def set_active(self, active: bool):
        if active:
            self.trigger.setAttribute("aria-selected", "true")
            self.trigger.setAttribute("data-state", "active")
            self.trigger.setAttribute("tabindex", "0")
            self.content.setAttribute("data-state", "active")
            self.content.setAttribute("style", "display: block")
        else:
            self.trigger.setAttribute("aria-selected", "false")
            self.trigger.setAttribute("data-state", "inactive")
            self.trigger.setAttribute("tabindex", "-1")
            self.content.setAttribute("data-state", "inactive")
            self.content.setAttribute("style", "display: none")


@js
class TabGroup(Widget):
    def __init__(self, *tabs: Tab, default_value: str):
        super().__init__()
        tab_list = tag(
            "div",
            tw("inline-flex h-9 w-fit items-center rounded-lg bg-slate-100 p-1"),
            {
                "aria-orientation": "horizontal",
                "data-slot": "tabs-list",
                "role": "tablist",
            },
        )
        contents: list[HTMLElement] = []
        group_id = self.get_component_id()
        tab_index = 0
        for tab in tabs:
            tab.link(group_id + "-tab-" + str(tab_index))
            tab.set_active(tab.value == default_value)
            tab_list.append(tab.trigger)
            contents.append(tab.content)
            tab_index += 1
        self.add(
            tw("block w-full"),
            {"data-slot": "tabs", "value": default_value},
            tab_list,
            *contents,
        )
        self.addEventListener("click", self.clicked)
        self.addEventListener("keydown", self.keydown)

    def current_value(self) -> str:
        value = self.getAttribute("value")
        if value is None:
            return ""
        return value

    def select(self, value: str, focus: bool = False):
        triggers: list[HTMLElement] = self.querySelectorAll("[data-slot=tabs-trigger]")
        contents = self.querySelectorAll("[data-slot=tabs-content]")
        for trigger in triggers:
            active = trigger.getAttribute("data-value") == value
            trigger.setAttribute("aria-selected", "true" if active else "false")
            trigger.setAttribute("data-state", "active" if active else "inactive")
            trigger.setAttribute("tabindex", "0" if active else "-1")
            if active and focus:
                trigger.focus()
        for content in contents:
            active = content.getAttribute("data-value") == value
            content.setAttribute("data-state", "active" if active else "inactive")
            content.setAttribute("style", "display: block" if active else "display: none")
        self.setAttribute("value", value)

    def clicked(self, event: Event):
        target = cast(Element, event.target)
        trigger = target.closest("[data-slot=tabs-trigger]")
        if trigger is not None:
            value = trigger.getAttribute("data-value")
            if value is not None:
                self.select(value)

    def keydown(self, event: KeyboardEvent):
        if (
            event.key != "ArrowLeft"
            and event.key != "ArrowRight"
            and event.key != "Home"
            and event.key != "End"
        ):
            return
        target = cast(Element, event.target)
        trigger = target.closest("[data-slot=tabs-trigger]")
        if trigger is None:
            return
        triggers: list[HTMLElement] = self.querySelectorAll("[data-slot=tabs-trigger]")
        first_trigger: HTMLElement | None = None
        last_trigger: HTMLElement | None = None
        previous_trigger: HTMLElement | None = None
        following_trigger: HTMLElement | None = None
        found_current = False
        for item in triggers:
            if first_trigger is None:
                first_trigger = item
            if item is trigger:
                found_current = True
                previous_trigger = last_trigger
            elif found_current and following_trigger is None:
                following_trigger = item
            last_trigger = item
        next_trigger: HTMLElement | None = None
        if event.key == "Home":
            next_trigger = first_trigger
        elif event.key == "End":
            next_trigger = last_trigger
        elif event.key == "ArrowLeft":
            next_trigger = previous_trigger
            if next_trigger is None:
                next_trigger = last_trigger
        else:
            next_trigger = following_trigger
            if next_trigger is None:
                next_trigger = first_trigger
        event.preventDefault()
        if next_trigger is not None:
            value = next_trigger.getAttribute("data-value")
            if value is not None:
                self.select(value, focus=True)
