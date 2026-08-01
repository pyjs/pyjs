from pyjs import js
from pyjs.web.domx import button, div, input, span, tag, tw


@js
def InputGroup(*children):
    return div(
        tw(
            "flex min-h-9 w-full items-center overflow-hidden rounded-md border border-slate-300 "
            "bg-white shadow-sm focus-within:border-slate-500 focus-within:ring-2 "
            "focus-within:ring-slate-200"
        ),
        {"data-slot": "input-group"},
        *children,
    )


@js
def InputGroupAddon(*children, align: str = "inline-start"):
    return div(
        tw(
            "flex h-full shrink-0 items-center gap-2 px-3 text-sm text-slate-500 "
            "data-[align=inline-end]:order-last"
        ),
        {"data-align": align, "data-slot": "input-group-addon"},
        *children,
    )


@js
def InputGroupButton(*children, label: str = ""):
    return button(
        tw(
            "inline-flex size-7 items-center justify-center rounded-sm hover:bg-slate-100"
        ),
        {"aria-label": label, "data-slot": "input-group-button", "type": "button"},
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
