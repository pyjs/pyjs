from pyjs import js
from pyjs.web.domx import div, tw


@js
def BubbleGroup(*children):
    return div(
        tw("flex flex-wrap items-center gap-2"), {"data-slot": "bubble-group"}, *children
    )


@js
def Bubble(*children, variant: str = "default"):
    return div(
        tw(
            "flex w-fit max-w-[85%] items-end gap-2 rounded-2xl bg-slate-100 px-3 py-2 "
            "text-sm text-slate-950 data-[variant=sent]:ml-auto data-[variant=sent]:bg-slate-950 "
            "data-[variant=sent]:text-white"
        ),
        {"data-slot": "bubble", "data-variant": variant},
        *children,
    )


@js
def BubbleContent(*children):
    return div(
        tw("min-w-0 whitespace-pre-wrap"), {"data-slot": "bubble-content"}, *children
    )


@js
def BubbleReactions(*children):
    return div(
        tw("flex items-center gap-1 text-xs text-slate-500"),
        {"data-slot": "bubble-reactions"},
        *children,
    )
