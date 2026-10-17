from typing import cast

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import button, div, input, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget


@js
class InputGroup(Widget):
    def __init__(self, *children, invalid: bool = False):
        super().__init__()
        self.add(
            tw(
                "flex min-h-9 w-full items-center overflow-hidden rounded-md border "
                "border-slate-300 bg-white shadow-sm focus-within:border-slate-500 "
                "focus-within:ring-2 focus-within:ring-slate-200 "
                "data-[invalid=true]:border-red-400 data-[invalid=true]:ring-red-200 "
                "has-[[data-align=block-start]]:h-auto has-[[data-align=block-start]]:flex-col "
                "has-[[data-align=block-end]]:h-auto has-[[data-align=block-end]]:flex-col"
            ),
            {
                "data-invalid": "true" if invalid else "false",
                "data-slot": "input-group",
                "role": "group",
            },
            *children,
        )

    def initialize(self):
        self.addEventListener("click", self.focus_control)

    def focus_control(self, event: Event) -> None:
        target = cast(Element, event.target)
        if target.closest("button,a,[data-slot=input-group-button]") is not None:
            return
        control = self.querySelector("[data-slot=input-group-control]")
        if isinstance(control, HTMLElement):
            control.focus()


@js
def InputGroupAddon(*children, align: str = "inline-start"):
    return div(
        tw(
            "flex h-full shrink-0 items-center gap-2 px-3 text-sm text-slate-500 "
            "data-[align=inline-end]:order-last data-[align=block-start]:w-full "
            "data-[align=block-end]:order-last data-[align=block-end]:w-full"
        ),
        {"data-align": align, "data-slot": "input-group-addon"},
        *children,
    )


@js
def InputGroupButton(*children, label: str = "", size: str = "sm"):
    return button(
        tw(
            "inline-flex size-7 items-center justify-center rounded-sm hover:bg-slate-100 "
            "data-[size=xs]:size-6 data-[size=icon-xs]:size-6 data-[size=icon-sm]:size-7"
        ),
        {
            "aria-label": label,
            "data-size": size,
            "data-slot": "input-group-button",
            "type": "button",
        },
        *children,
    )


@js
def InputGroupText(*children):
    return span(
        tw("text-sm text-slate-500"), {"data-slot": "input-group-text"}, *children
    )


@js
def InputGroupInput(
    input_type: str = "text",
    placeholder: str = "",
    name: str = "",
):
    return input(
        tw(
            "h-9 min-w-0 flex-1 border-0 bg-transparent px-3 text-sm outline-none "
            "placeholder:text-slate-400"
        ),
        {
            "data-slot": "input-group-control",
            "name": name,
            "placeholder": placeholder,
            "type": input_type,
        },
    )


@js
def InputGroupTextarea(placeholder: str = "", name: str = ""):
    return tag(
        "textarea",
        tw(
            "min-h-20 min-w-0 flex-1 resize-none border-0 bg-transparent px-3 py-2 "
            "text-sm outline-none placeholder:text-slate-400"
        ),
        {"data-slot": "input-group-control", "name": name, "placeholder": placeholder},
    )
