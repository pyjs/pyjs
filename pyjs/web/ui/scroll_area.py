from pyjs import js
from pyjs.web.domx import div, tw


@js
def ScrollArea(*children, height: str = "12rem"):
    return div(
        tw(
            "relative overflow-auto rounded-md focus-visible:outline-none focus-visible:ring-2"
        ),
        {
            "data-slot": "scroll-area",
            "style": "max-height: " + height,
            "tabindex": "0",
        },
        *children,
    )


@js
def ScrollBar(orientation: str = "vertical"):
    return div(
        tw("pointer-events-none absolute opacity-0"),
        {
            "aria-hidden": "true",
            "data-orientation": orientation,
            "data-slot": "scroll-bar",
        },
    )
