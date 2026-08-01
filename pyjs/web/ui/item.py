from pyjs import js
from pyjs.web.domx import div, p, tag, tw


@js
def ItemGroup(*children):
    return div(tw("grid gap-2"), {"data-slot": "item-group", "role": "list"}, *children)


@js
def ItemSeparator():
    return tag(
        "div",
        tw("h-px bg-slate-200"),
        {"data-slot": "item-separator", "role": "separator"},
    )


@js
def Item(*children, variant: str = "default", size: str = "default"):
    return div(
        tw(
            "flex items-center gap-3 rounded-lg border border-transparent p-3 text-sm "
            "data-[variant=outline]:border-slate-200 data-[variant=muted]:bg-slate-100 "
            "data-[size=sm]:p-2"
        ),
        {
            "data-size": size,
            "data-slot": "item",
            "data-variant": variant,
            "role": "listitem",
        },
        *children,
    )


@js
def ItemMedia(*children, variant: str = "default"):
    return div(
        tw(
            "flex size-10 shrink-0 items-center justify-center rounded-md bg-slate-100 "
            "data-[variant=image]:overflow-hidden data-[variant=image]:bg-transparent"
        ),
        {"data-slot": "item-media", "data-variant": variant},
        *children,
    )


@js
def ItemContent(*children):
    return div(tw("min-w-0 flex-1"), {"data-slot": "item-content"}, *children)


@js
def ItemTitle(*children):
    return div(tw("font-medium text-slate-950"), {"data-slot": "item-title"}, *children)


@js
def ItemDescription(*children):
    return p(tw("text-sm text-slate-500"), {"data-slot": "item-description"}, *children)


@js
def ItemActions(*children):
    return div(
        tw("ml-auto flex items-center gap-2"), {"data-slot": "item-actions"}, *children
    )


@js
def ItemHeader(*children):
    return div(tw("flex items-center gap-2"), {"data-slot": "item-header"}, *children)


@js
def ItemFooter(*children):
    return div(tw("flex items-center gap-2"), {"data-slot": "item-footer"}, *children)
