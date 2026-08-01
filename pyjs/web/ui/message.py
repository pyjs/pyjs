from pyjs import js
from pyjs.web.domx import div, tw


@js
def MessageGroup(*children):
    return div(
        tw("flex flex-col gap-5"),
        {"aria-live": "polite", "data-slot": "message-group", "role": "log"},
        *children,
    )


@js
def Message(*children, sent: bool = False):
    return div(
        tw(
            "flex items-start gap-3 data-[sent=true]:flex-row-reverse data-[sent=true]:text-right"
        ),
        {"data-sent": "true" if sent else "false", "data-slot": "message"},
        *children,
    )


@js
def MessageAvatar(*children):
    return div(
        tw(
            "flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full "
            "bg-slate-100"
        ),
        {"data-slot": "message-avatar"},
        *children,
    )


@js
def MessageContent(*children):
    return div(tw("min-w-0 max-w-[80%]"), {"data-slot": "message-content"}, *children)


@js
def MessageHeader(*children):
    return div(
        tw("mb-1 flex items-center gap-2 text-xs text-slate-500"),
        {"data-slot": "message-header"},
        *children,
    )


@js
def MessageFooter(*children):
    return div(
        tw("mt-1 flex items-center gap-2 text-xs text-slate-500"),
        {"data-slot": "message-footer"},
        *children,
    )
