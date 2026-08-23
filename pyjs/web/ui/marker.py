from pyjs import js
from pyjs.web.domx import div, span, tw


@js
def Marker(*children, variant: str = "default"):
    return div(
        tw(
            "group/marker relative flex min-h-4 w-full items-center gap-2 text-left text-sm "
            "text-slate-500 data-[variant=separator]:before:mr-1 "
            "data-[variant=separator]:before:h-px "
            "data-[variant=separator]:before:min-w-0 "
            "data-[variant=separator]:before:flex-1 "
            "data-[variant=separator]:before:bg-slate-200 "
            "data-[variant=separator]:after:ml-1 data-[variant=separator]:after:h-px "
            "data-[variant=separator]:after:min-w-0 "
            "data-[variant=separator]:after:flex-1 "
            "data-[variant=separator]:after:bg-slate-200 "
            "data-[variant=border]:border-b data-[variant=border]:border-slate-200 "
            "data-[variant=border]:pb-2"
        ),
        {"data-slot": "marker", "data-variant": variant},
        *children,
    )


@js
def MarkerIcon(*children):
    return span(
        tw("inline-flex size-4 shrink-0 items-center justify-center"),
        {"aria-hidden": "true", "data-slot": "marker-icon"},
        *children,
    )


@js
def MarkerContent(*children):
    return span(
        tw(
            "min-w-0 break-words group-data-[variant=separator]/marker:flex-none "
            "group-data-[variant=separator]/marker:text-center"
        ),
        {"data-slot": "marker-content"},
        *children,
    )
