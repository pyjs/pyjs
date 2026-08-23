from pyjs import js
from pyjs.web.domx import div, tw


@js
def BubbleGroup(*children):
    return div(
        tw("flex min-w-0 flex-col gap-2"),
        {"data-slot": "bubble-group"},
        *children,
    )


@js
def Bubble(*children, variant: str = "default", align: str = "start"):
    return div(
        tw(
            "group/bubble relative flex w-fit max-w-[80%] min-w-0 flex-col gap-1 "
            "group-data-[align=end]/message:self-end data-[align=end]:self-end "
            "data-[variant=ghost]:max-w-full "
            "data-[variant=default]:[&>[data-slot=bubble-content]]:bg-violet-600 "
            "data-[variant=default]:[&>[data-slot=bubble-content]]:text-white "
            "data-[variant=secondary]:[&>[data-slot=bubble-content]]:bg-slate-200 "
            "data-[variant=muted]:[&>[data-slot=bubble-content]]:bg-slate-100 "
            "data-[variant=tinted]:[&>[data-slot=bubble-content]]:bg-violet-100 "
            "data-[variant=tinted]:[&>[data-slot=bubble-content]]:text-violet-950 "
            "data-[variant=outline]:[&>[data-slot=bubble-content]]:border-slate-300 "
            "data-[variant=outline]:[&>[data-slot=bubble-content]]:bg-white "
            "data-[variant=ghost]:[&>[data-slot=bubble-content]]:rounded-none "
            "data-[variant=ghost]:[&>[data-slot=bubble-content]]:border-0 "
            "data-[variant=ghost]:[&>[data-slot=bubble-content]]:bg-transparent "
            "data-[variant=ghost]:[&>[data-slot=bubble-content]]:p-0 "
            "data-[variant=destructive]:[&>[data-slot=bubble-content]]:bg-red-50 "
            "data-[variant=destructive]:[&>[data-slot=bubble-content]]:text-red-700"
        ),
        {"data-align": align, "data-slot": "bubble", "data-variant": variant},
        *children,
    )


@js
def BubbleContent(*children):
    return div(
        tw(
            "w-fit max-w-full min-w-0 overflow-hidden rounded-xl border border-transparent "
            "px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words "
            "group-data-[align=end]/bubble:self-end"
        ),
        {"data-slot": "bubble-content"},
        *children,
    )


@js
def BubbleReactions(
    *children,
    side: str = "bottom",
    align: str = "end",
    label: str = "Message reactions",
):
    return div(
        tw(
            "absolute z-10 flex w-fit shrink-0 items-center justify-center gap-1 rounded-full "
            "bg-slate-100 px-1.5 py-0.5 text-sm ring-2 ring-white "
            "data-[side=top]:top-0 data-[side=top]:-translate-y-3/4 "
            "data-[side=bottom]:bottom-0 data-[side=bottom]:translate-y-3/4 "
            "data-[align=start]:left-3 data-[align=end]:right-3"
        ),
        {
            "aria-label": label,
            "data-align": align,
            "data-side": side,
            "data-slot": "bubble-reactions",
            "role": "group",
        },
        *children,
    )
