from pyjs import js
from pyjs.web.domx import button, div, span, tw


@js
def Attachment(
    *children,
    state: str = "done",
    size: str = "default",
    orientation: str = "horizontal",
):
    return div(
        tw(
            "group/attachment relative flex w-fit max-w-full min-w-0 shrink-0 flex-wrap "
            "rounded-xl border border-slate-200 bg-white text-slate-950 transition-colors "
            "focus-within:ring-2 focus-within:ring-violet-300 has-[>a,>button]:hover:bg-slate-50 "
            "data-[state=error]:border-red-300 data-[state=idle]:border-dashed "
            "data-[size=default]:gap-2 data-[size=default]:p-2 data-[size=sm]:gap-2 "
            "data-[size=sm]:p-1.5 data-[size=sm]:text-xs data-[size=xs]:gap-1.5 "
            "data-[size=xs]:rounded-lg data-[size=xs]:p-1 data-[size=xs]:text-xs "
            "data-[orientation=horizontal]:min-w-40 data-[orientation=horizontal]:items-center "
            "data-[orientation=vertical]:w-28 data-[orientation=vertical]:flex-col"
        ),
        {
            "data-orientation": orientation,
            "data-size": size,
            "data-slot": "attachment",
            "data-state": state,
        },
        *children,
    )


@js
def AttachmentMedia(*children, variant: str = "icon"):
    return div(
        tw(
            "relative flex aspect-square w-10 shrink-0 items-center justify-center "
            "overflow-hidden rounded-lg bg-slate-100 text-slate-700 "
            "group-data-[orientation=vertical]/attachment:w-full "
            "group-data-[size=sm]/attachment:w-8 group-data-[size=xs]/attachment:w-7 "
            "group-data-[size=xs]/attachment:rounded-md "
            "group-data-[state=error]/attachment:bg-red-50 "
            "group-data-[state=error]/attachment:text-red-600 "
            "data-[variant=image]:opacity-70 data-[variant=image]:[&_img]:size-full "
            "data-[variant=image]:[&_img]:object-cover "
            "group-data-[state=done]/attachment:data-[variant=image]:opacity-100"
        ),
        {"data-slot": "attachment-media", "data-variant": variant},
        *children,
    )


@js
def AttachmentContent(*children):
    return div(
        tw("max-w-full min-w-0 flex-1 leading-tight"),
        {"data-slot": "attachment-content"},
        *children,
    )


@js
def AttachmentTitle(*children):
    return span(
        tw("block max-w-full min-w-0 truncate font-medium"),
        {"data-slot": "attachment-title"},
        *children,
    )


@js
def AttachmentDescription(*children):
    return span(
        tw(
            "mt-0.5 block max-w-full min-w-0 truncate text-xs text-slate-500 "
            "group-data-[state=error]/attachment:text-red-600"
        ),
        {"data-slot": "attachment-description"},
        *children,
    )


@js
def AttachmentActions(*children):
    return div(
        tw(
            "relative z-20 flex shrink-0 items-center "
            "group-data-[orientation=vertical]/attachment:absolute "
            "group-data-[orientation=vertical]/attachment:right-2 "
            "group-data-[orientation=vertical]/attachment:top-2"
        ),
        {"data-slot": "attachment-actions"},
        *children,
    )


@js
def AttachmentAction(label: str, *children):
    return button(
        tw(
            "inline-flex size-7 items-center justify-center rounded-md text-slate-500 "
            "outline-none hover:bg-slate-200 hover:text-slate-950 focus-visible:ring-2 "
            "focus-visible:ring-violet-300"
        ),
        {"aria-label": label, "data-slot": "attachment-action", "type": "button"},
        *children,
    )


@js
def AttachmentTrigger(label: str):
    return button(
        tw("absolute inset-0 z-10 rounded-xl outline-none focus-visible:ring-2"),
        {"aria-label": label, "data-slot": "attachment-trigger", "type": "button"},
    )


@js
def AttachmentGroup(*children):
    return div(
        tw(
            "flex min-w-0 snap-x snap-mandatory gap-3 overflow-x-auto overscroll-x-contain "
            "py-1 *:data-[slot=attachment]:flex-none "
            "*:data-[slot=attachment]:snap-start"
        ),
        {"data-slot": "attachment-group", "role": "list"},
        *children,
    )
