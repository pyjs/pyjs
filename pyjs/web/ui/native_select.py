from pyjs import js
from pyjs.web.domx import div, tag, tw


@js
def NativeSelect(*children, name: str = "", label: str = ""):
    return div(
        tw("relative inline-flex w-full items-center"),
        {"data-slot": "native-select-wrapper"},
        tag(
            "select",
            tw(
                "h-9 w-full appearance-none rounded-md border border-slate-300 bg-white px-3 "
                "pr-8 text-sm text-slate-950 shadow-sm outline-none focus:border-slate-500 "
                "focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
            ),
            {"aria-label": label, "data-slot": "native-select", "name": name},
            *children,
        ),
        tag(
            "span",
            tw("pointer-events-none absolute right-3 text-xs text-slate-500"),
            {"aria-hidden": "true"},
            "▼",
        ),
    )


@js
def NativeSelectOption(
    value: str, *children, selected: bool = False, disabled: bool = False
):
    attributes = {"data-slot": "native-select-option", "value": value}
    if selected:
        attributes["selected"] = ""
    if disabled:
        attributes["disabled"] = ""
    return tag("option", attributes, *children)


@js
def NativeSelectOptGroup(label: str, *children):
    return tag(
        "optgroup",
        {"data-slot": "native-select-optgroup", "label": label},
        *children,
    )
