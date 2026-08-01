from pyjs import js
from pyjs.web.domx import button, div, p, tag, tw


@js
def Attachment(*children, variant: str = "default"):
    return div(
        tw(
            "group flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 "
            "text-sm text-slate-950 data-[variant=ghost]:border-transparent "
            "data-[variant=ghost]:bg-transparent"
        ),
        {"data-slot": "attachment", "data-variant": variant},
        *children,
    )


@js
def AttachmentMedia(*children, variant: str = "default"):
    return div(
        tw(
            "flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md "
            "bg-slate-100 text-slate-600 data-[variant=image]:bg-transparent"
        ),
        {"data-slot": "attachment-media", "data-variant": variant},
        *children,
    )


@js
def AttachmentContent(*children):
    return div(tw("min-w-0 flex-1"), {"data-slot": "attachment-content"}, *children)


@js
def AttachmentTitle(*children):
    return div(
        tw("truncate font-medium text-slate-950"),
        {"data-slot": "attachment-title"},
        *children,
    )


@js
def AttachmentDescription(*children):
    return p(
        tw("truncate text-xs text-slate-500"),
        {"data-slot": "attachment-description"},
        *children,
    )


@js
def AttachmentActions(*children):
    return div(
        tw("flex shrink-0 items-center gap-1"),
        {"data-slot": "attachment-actions"},
        *children,
    )


@js
def AttachmentAction(label: str, *children):
    return button(
        tw(
            "inline-flex size-8 items-center justify-center rounded-md hover:bg-slate-100"
        ),
        {"aria-label": label, "data-slot": "attachment-action", "type": "button"},
        *children,
    )


@js
def AttachmentGroup(*children):
    return tag(
        "div",
        tw("grid gap-2"),
        {"data-slot": "attachment-group", "role": "list"},
        *children,
    )
