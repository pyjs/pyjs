from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Empty(*children):
    return tag(
        "div",
        tw(
            "flex min-h-64 w-full flex-col items-center justify-center gap-6 rounded-lg "
            "border border-dashed border-slate-300 p-8 text-center"
        ),
        {"data-slot": "empty"},
        *children,
    )


@js
def EmptyHeader(*children):
    return tag(
        "div",
        tw("flex max-w-sm flex-col items-center gap-2"),
        {"data-slot": "empty-header"},
        *children,
    )


@js
def EmptyMedia(*children, variant: str = "default"):
    return tag(
        "div",
        tw(
            "flex shrink-0 items-center justify-center data-[variant=icon]:size-12 "
            "data-[variant=icon]:rounded-lg data-[variant=icon]:bg-slate-100 "
            "data-[variant=icon]:text-xl"
        ),
        {"data-slot": "empty-icon", "data-variant": variant},
        *children,
    )


@js
def EmptyTitle(*children):
    return tag(
        "div",
        tw("font-semibold text-slate-950"),
        {"data-slot": "empty-title"},
        *children,
    )


@js
def EmptyDescription(*children):
    return tag(
        "p",
        tw("text-sm leading-6 text-slate-500"),
        {"data-slot": "empty-description"},
        *children,
    )


@js
def EmptyContent(*children):
    return tag(
        "div",
        tw("flex max-w-sm flex-col items-center gap-2"),
        {"data-slot": "empty-content"},
        *children,
    )
