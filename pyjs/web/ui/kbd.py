from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Kbd(*children):
    return tag(
        "kbd",
        tw(
            "pointer-events-none inline-flex min-w-5 items-center justify-center rounded "
            "border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono text-xs "
            "font-medium text-slate-700 shadow-sm select-none"
        ),
        {"data-slot": "kbd"},
        *children,
    )


@js
def KbdGroup(*children):
    return tag(
        "kbd",
        tw("inline-flex items-center gap-1"),
        {"data-slot": "kbd-group"},
        *children,
    )
