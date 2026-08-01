from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Alert(*children, variant: str = "default"):
    if variant == "destructive":
        style = tw(
            "relative w-full rounded-lg border border-red-200 bg-white px-4 py-3 "
            "text-sm text-red-700 shadow-sm"
        )
    else:
        style = tw(
            "relative w-full rounded-lg border border-slate-200 bg-white px-4 py-3 "
            "text-sm text-slate-950 shadow-sm"
        )
    return tag(
        "div",
        style,
        {"data-slot": "alert", "data-variant": variant, "role": "alert"},
        *children,
    )


@js
def AlertTitle(*children):
    return tag(
        "div",
        tw("font-medium tracking-tight"),
        {"data-slot": "alert-title"},
        *children,
    )


@js
def AlertDescription(*children):
    return tag(
        "div",
        tw("mt-1 text-sm leading-relaxed opacity-80"),
        {"data-slot": "alert-description"},
        *children,
    )


@js
def AlertAction(*children):
    return tag(
        "div",
        tw("absolute right-4 top-3"),
        {"data-slot": "alert-action"},
        *children,
    )
