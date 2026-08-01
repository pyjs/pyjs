from pyjs import js
from pyjs.web.domx import a, button, div, tag, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget


@js
def NavigationMenu(*children, label: str = "Main navigation"):
    return tag(
        "nav",
        tw("relative flex max-w-max items-center"),
        {"aria-label": label, "data-slot": "navigation-menu"},
        *children,
    )


@js
def NavigationMenuList(*children):
    return tag(
        "ul",
        tw("flex list-none items-center gap-1"),
        {"data-slot": "navigation-menu-list"},
        *children,
    )


@js
class NavigationMenuItem(Widget):
    def __init__(self, trigger: HTMLElement, content: HTMLElement):
        super().__init__()
        self.trigger = trigger
        self.content = content
        self.add(
            tw("relative list-item"),
            {
                "data-slot": "navigation-menu-item",
                "data-state": "closed",
                "role": "listitem",
            },
            self.trigger,
            self.content,
        )
        self.trigger.addEventListener("click", self.toggle)

    def is_open(self) -> bool:
        return self.getAttribute("data-state") == "open"

    def set_open(self, open: bool):
        self.setAttribute("data-state", "open" if open else "closed")
        self.trigger.setAttribute("aria-expanded", "true" if open else "false")
        if open:
            self.content.removeAttribute("hidden")
        else:
            self.content.setAttribute("hidden", "")

    def toggle(self, event: Event):
        self.set_open(not self.is_open())


@js
def NavigationMenuTrigger(*children):
    return button(
        tw(
            "inline-flex h-9 items-center rounded-md px-3 text-sm font-medium hover:bg-slate-100 "
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
        ),
        {
            "aria-expanded": "false",
            "data-slot": "navigation-menu-trigger",
            "type": "button",
        },
        *children,
    )


@js
def NavigationMenuContent(*children):
    return div(
        tw(
            "absolute left-0 top-full z-50 mt-1 min-w-64 rounded-md border bg-white p-3 shadow-md"
        ),
        {"data-slot": "navigation-menu-content", "hidden": ""},
        *children,
    )


@js
def NavigationMenuLink(href: str, *children, current: bool = False):
    attributes = {"data-slot": "navigation-menu-link", "href": href}
    if current:
        attributes["aria-current"] = "page"
    return a(
        tw("block rounded-md px-3 py-2 text-sm hover:bg-slate-100"),
        attributes,
        *children,
    )


@js
def NavigationMenuViewport(*children):
    return div({"data-slot": "navigation-menu-viewport"}, *children)


@js
def NavigationMenuIndicator():
    return div(
        tw("h-1 w-1 rotate-45 bg-slate-200"),
        {"aria-hidden": "true", "data-slot": "navigation-menu-indicator"},
    )
