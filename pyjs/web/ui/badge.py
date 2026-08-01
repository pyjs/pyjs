from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Badge(*children, variant: str = "default"):
    if variant == "secondary":
        style = tw(
            "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden "
            "whitespace-nowrap rounded-full border border-transparent bg-slate-100 px-2 "
            "py-0.5 text-xs font-medium text-slate-900"
        )
    elif variant == "destructive":
        style = tw(
            "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden "
            "whitespace-nowrap rounded-full border border-transparent bg-red-600 px-2 "
            "py-0.5 text-xs font-medium text-white"
        )
    elif variant == "outline":
        style = tw(
            "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden "
            "whitespace-nowrap rounded-full border border-slate-300 bg-transparent px-2 "
            "py-0.5 text-xs font-medium text-slate-950"
        )
    elif variant == "ghost":
        style = tw(
            "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden "
            "whitespace-nowrap rounded-full border border-transparent bg-transparent px-2 "
            "py-0.5 text-xs font-medium text-slate-700"
        )
    elif variant == "link":
        style = tw(
            "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden "
            "whitespace-nowrap rounded-full border border-transparent bg-transparent px-2 "
            "py-0.5 text-xs font-medium text-slate-950 underline underline-offset-4"
        )
    else:
        style = tw(
            "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden "
            "whitespace-nowrap rounded-full border border-transparent bg-slate-950 px-2 "
            "py-0.5 text-xs font-medium text-white"
        )
    return tag(
        "span",
        style,
        {"data-slot": "badge", "data-variant": variant},
        *children,
    )
