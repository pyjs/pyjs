from pyjs import js
from pyjs.web.domx import div, tw


@js
def MessageGroup(*children):
    return div(
        tw("flex min-w-0 flex-col gap-2"),
        {"aria-live": "polite", "data-slot": "message-group", "role": "log"},
        *children,
    )


@js
def Message(*children, align: str = "start"):
    return div(
        tw(
            "group/message relative flex w-full min-w-0 gap-2 text-sm "
            "data-[align=end]:flex-row-reverse"
        ),
        {"data-align": align, "data-slot": "message"},
        *children,
    )


@js
def MessageAvatar(*children):
    return div(
        tw(
            "flex size-9 shrink-0 items-center justify-center self-end overflow-hidden "
            "rounded-full bg-slate-100 text-xs font-semibold text-slate-600"
        ),
        {"data-slot": "message-avatar"},
        *children,
    )


@js
def MessageContent(*children):
    return div(
        tw(
            "flex w-full min-w-0 flex-col gap-2.5 break-words "
            "group-data-[align=end]/message:*:data-slot:self-end"
        ),
        {"data-slot": "message-content"},
        *children,
    )


@js
def MessageHeader(*children):
    return div(
        tw(
            "flex max-w-full min-w-0 items-center gap-2 px-3 text-xs font-medium "
            "text-slate-500"
        ),
        {"data-slot": "message-header"},
        *children,
    )


@js
def MessageFooter(*children):
    return div(
        tw(
            "flex max-w-full min-w-0 items-center gap-2 px-3 text-xs font-medium "
            "text-slate-500 group-data-[align=end]/message:justify-end"
        ),
        {"data-slot": "message-footer"},
        *children,
    )
