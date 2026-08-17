from typing import cast

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import a, button, div, input, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget
from pyjs.web.ui.sheet import Sheet, SheetContent, SheetTrigger


@js
def Sidebar(*children, side: str = "left"):
    return tag(
        "aside",
        tw(
            "flex w-64 shrink-0 flex-col border-slate-200 bg-slate-50 text-slate-950 "
            "data-[side=left]:border-r data-[side=right]:border-l "
            "group-data-[state=collapsed]/sidebar-layout:w-0 "
            "group-data-[state=collapsed]/sidebar-layout:overflow-hidden"
        ),
        {"data-side": side, "data-slot": "sidebar"},
        *children,
    )


@js
def SidebarTrigger(*children, label: str = "Toggle sidebar"):
    return button(
        tw(
            "inline-flex size-9 items-center justify-center rounded-md hover:bg-slate-100"
        ),
        {
            "aria-label": label,
            "data-sidebar-toggle": "",
            "data-slot": "sidebar-trigger",
            "type": "button",
        },
        *children,
    )


@js
def SidebarInset(*children):
    return tag("main", tw("min-w-0 flex-1"), {"data-slot": "sidebar-inset"}, *children)


@js
def SidebarInput(placeholder: str = "Search", name: str = ""):
    return input(
        tw(
            "h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-sm outline-none"
        ),
        {"data-slot": "sidebar-input", "name": name, "placeholder": placeholder},
    )


@js
def SidebarHeader(*children):
    return div(tw("grid gap-2 p-3"), {"data-slot": "sidebar-header"}, *children)


@js
def SidebarFooter(*children):
    return div(tw("mt-auto grid gap-2 p-3"), {"data-slot": "sidebar-footer"}, *children)


@js
def SidebarContent(*children):
    return div(
        tw("min-h-0 flex-1 overflow-auto p-2"),
        {"data-slot": "sidebar-content"},
        *children,
    )


@js
def SidebarGroup(*children):
    return div(tw("grid gap-1 p-2"), {"data-slot": "sidebar-group"}, *children)


@js
def SidebarGroupLabel(*children):
    return div(
        tw("px-2 py-1 text-xs font-medium text-slate-500"),
        {"data-slot": "sidebar-group-label"},
        *children,
    )


@js
def SidebarGroupContent(*children):
    return div({"data-slot": "sidebar-group-content"}, *children)


@js
def SidebarMenu(*children):
    return tag("ul", tw("grid gap-1"), {"data-slot": "sidebar-menu"}, *children)


@js
def SidebarMenuItem(*children):
    return tag("li", {"data-slot": "sidebar-menu-item"}, *children)


@js
def SidebarMenuButton(href: str, *children, current: bool = False):
    attributes = {"data-slot": "sidebar-menu-button", "href": href}
    if current:
        attributes["aria-current"] = "page"
    return a(
        tw(
            "flex h-8 items-center gap-2 rounded-md px-2 text-sm hover:bg-slate-200 "
            "aria-[current=page]:bg-slate-200 aria-[current=page]:font-medium"
        ),
        attributes,
        *children,
    )


@js
def SidebarMenuBadge(*children):
    return tag(
        "span",
        tw("ml-auto rounded-full bg-slate-200 px-1.5 text-xs"),
        {"data-slot": "sidebar-menu-badge"},
        *children,
    )


@js
def SidebarSeparator():
    return div(tw("mx-2 h-px bg-slate-200"), {"data-slot": "sidebar-separator"})


@js
class MobileSidebar(Sheet):
    def __init__(
        self,
        label: str,
        *children,
        side: str = "left",
        trigger_text: str = "☰",
        show_close: bool = True,
        trigger_style: dict[str, str] | None = None,
        content_style: dict[str, str] | None = None,
        surface_style: dict[str, str] | None = None,
    ):
        if trigger_style is None:
            trigger_style = tw(
                "inline-flex size-9 items-center justify-center rounded-md "
                "hover:bg-slate-100 md:hidden"
            )
        trigger = SheetTrigger(
            trigger_style,
            trigger_text,
        )
        trigger.setAttribute("aria-label", "Open navigation")
        content = SheetContent(
            label,
            *children,
            side=side,
            show_close=show_close,
        )
        content.dialog_element.setAttribute("data-mobile", "true")
        if content_style is not None:
            tag(content.dialog_element, content_style)
        if surface_style is not None:
            tag(content.surface, surface_style)
        super().__init__(trigger, content)
        self.setAttribute("data-slot", "mobile-sidebar")


@js
class SidebarLayout(Widget):
    def __init__(self, sidebar: Element, inset: Element, *, default_open: bool = True):
        super().__init__()
        self.add(
            tw("group/sidebar-layout flex min-h-screen w-full"),
            {
                "data-slot": "sidebar-layout",
                "data-state": "expanded" if default_open else "collapsed",
            },
            sidebar,
            inset,
        )
        self.addEventListener("click", self.clicked)

    def is_open(self) -> bool:
        return self.getAttribute("data-state") == "expanded"

    def set_open(self, open: bool):
        self.setAttribute("data-state", "expanded" if open else "collapsed")
        triggers: list[Element] = self.querySelectorAll("[data-sidebar-toggle]")
        for trigger in triggers:
            trigger.setAttribute("aria-expanded", "true" if open else "false")

    def toggle(self):
        self.set_open(not self.is_open())

    def clicked(self, event: Event):
        target = cast(Element, event.target)
        if target.closest("[data-sidebar-toggle]") is not None:
            self.toggle()
