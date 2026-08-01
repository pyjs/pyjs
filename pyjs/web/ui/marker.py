from pyjs import js
from pyjs.web.domx import span, tw


@js
def Marker(*children, variant: str = "default"):
    return span(
        tw(
            "inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2 py-1 text-xs "
            "font-medium text-slate-700 data-[variant=outline]:border "
            "data-[variant=outline]:border-slate-300 data-[variant=outline]:bg-white"
        ),
        {"data-slot": "marker", "data-variant": variant},
        *children,
    )


@js
def MarkerIcon(*children):
    return span(
        tw("inline-flex size-3 items-center justify-center"),
        {"data-slot": "marker-icon"},
        *children,
    )


@js
def MarkerContent(*children):
    return span({"data-slot": "marker-content"}, *children)
