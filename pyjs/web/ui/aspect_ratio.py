from pyjs import js
from pyjs.web.domx import tag, tw


@js
def AspectRatio(*children, ratio: str):
    return tag(
        "div",
        tw("relative w-full overflow-hidden"),
        {"data-slot": "aspect-ratio", "style": "aspect-ratio: " + ratio},
        *children,
    )
