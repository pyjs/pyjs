from pyjs import js
from pyjs.web.domx import tag, tw


@js
def FieldSet(*children):
    return tag(
        "fieldset",
        tw("flex flex-col gap-6"),
        {"data-slot": "field-set"},
        *children,
    )


@js
def FieldLegend(*children):
    return tag(
        "legend",
        tw("mb-3 text-base font-semibold text-slate-950"),
        {"data-slot": "field-legend"},
        *children,
    )


@js
def FieldGroup(*children):
    return tag(
        "div",
        tw("flex w-full flex-col gap-5"),
        {"data-slot": "field-group"},
        *children,
    )


@js
def Field(*children, orientation: str = "vertical"):
    if orientation == "horizontal":
        style = tw("flex w-full items-start gap-3")
    else:
        style = tw("flex w-full flex-col gap-2")
    return tag(
        "div",
        style,
        {"data-orientation": orientation, "data-slot": "field", "role": "group"},
        *children,
    )


@js
def FieldContent(*children):
    return tag(
        "div",
        tw("flex flex-1 flex-col gap-1 leading-snug"),
        {"data-slot": "field-content"},
        *children,
    )


@js
def FieldLabel(*children):
    return tag(
        "label",
        tw("flex w-full flex-col items-start gap-2 text-sm font-medium text-slate-950"),
        {"data-slot": "field-label"},
        *children,
    )


@js
def FieldTitle(*children):
    return tag(
        "div",
        tw("font-medium text-slate-950"),
        {"data-slot": "field-title"},
        *children,
    )


@js
def FieldDescription(*children):
    return tag(
        "p",
        tw("text-sm font-normal leading-5 text-slate-500"),
        {"data-slot": "field-description"},
        *children,
    )


@js
def FieldError(*children):
    return tag(
        "div",
        tw("text-sm font-normal text-red-600"),
        {"data-slot": "field-error", "role": "alert"},
        *children,
    )
