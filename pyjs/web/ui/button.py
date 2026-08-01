from pyjs import js
from pyjs.web.domx import ProxyElement, button, tag, tw


@js
class Button(ProxyElement):
    def __init__(
        self,
        *children: object,
        variant: str = "default",
        size: str = "default",
    ):
        self.element = button(
            tw(
                "inline-flex h-9 shrink-0 items-center justify-center gap-2 whitespace-nowrap "
                "rounded-md bg-slate-950 px-4 text-sm font-medium text-white shadow-sm "
                "outline-none transition-colors hover:bg-slate-800 focus-visible:ring-2 "
                "focus-visible:ring-slate-400 disabled:pointer-events-none disabled:opacity-50 "
                "data-[variant=outline]:border data-[variant=outline]:border-slate-300 "
                "data-[variant=outline]:bg-white data-[variant=outline]:text-slate-950 "
                "data-[variant=outline]:hover:bg-slate-100 data-[variant=secondary]:bg-slate-100 "
                "data-[variant=secondary]:text-slate-950 data-[variant=secondary]:shadow-none "
                "data-[variant=ghost]:bg-transparent data-[variant=ghost]:text-slate-950 "
                "data-[variant=ghost]:shadow-none data-[variant=ghost]:hover:bg-slate-100 "
                "data-[variant=destructive]:bg-red-600 data-[variant=destructive]:hover:bg-red-500 "
                "data-[variant=link]:bg-transparent data-[variant=link]:text-slate-950 "
                "data-[variant=link]:shadow-none data-[variant=link]:underline "
                "data-[variant=link]:underline-offset-4 data-[size=xs]:h-7 data-[size=xs]:px-2 "
                "data-[size=xs]:text-xs data-[size=sm]:h-8 data-[size=sm]:px-3 "
                "data-[size=lg]:h-10 data-[size=lg]:px-6 data-[size=icon]:size-9 "
                "data-[size=icon]:px-0"
            ),
            {
                "data-size": size,
                "data-slot": "button",
                "data-variant": variant,
                "type": "button",
            },
            *children,
        )

    def on_click(self, callback: callable):
        self.element.addEventListener("click", callback)


@js
def ButtonGroup(*children, orientation: str = "horizontal"):
    return tag(
        "div",
        tw(
            "flex w-fit items-stretch data-[orientation=vertical]:flex-col "
            "[&>[data-slot=button]]:rounded-none [&>[data-slot=button]:first-child]:rounded-l-md "
            "[&>[data-slot=button]:last-child]:rounded-r-md "
            "data-[orientation=vertical]:[&>[data-slot=button]:first-child]:rounded-l-none "
            "data-[orientation=vertical]:[&>[data-slot=button]:first-child]:rounded-t-md "
            "data-[orientation=vertical]:[&>[data-slot=button]:last-child]:rounded-r-none "
            "data-[orientation=vertical]:[&>[data-slot=button]:last-child]:rounded-b-md"
        ),
        {"data-orientation": orientation, "data-slot": "button-group", "role": "group"},
        *children,
    )


@js
def ButtonGroupText(*children):
    return tag(
        "div",
        tw(
            "flex items-center border border-slate-300 bg-slate-50 px-3 text-sm text-slate-600"
        ),
        {"data-slot": "button-group-text"},
        *children,
    )


@js
def ButtonGroupSeparator(orientation: str = "vertical"):
    return tag(
        "div",
        tw("relative self-stretch bg-slate-300 data-[orientation=vertical]:w-px"),
        {
            "aria-hidden": "true",
            "data-orientation": orientation,
            "data-slot": "button-group-separator",
        },
    )
