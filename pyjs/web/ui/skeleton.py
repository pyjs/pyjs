from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Skeleton(width: str = "100%", height: str = "1rem"):
    return tag(
        "div",
        tw("animate-pulse rounded-md bg-slate-200"),
        {
            "aria-hidden": "true",
            "data-slot": "skeleton",
            "style": "width: " + width + "; height: " + height,
        },
    )
