from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Separator(orientation: str = "horizontal", decorative: bool = True):
    if orientation == "vertical":
        style = tw("h-full w-px shrink-0 self-stretch bg-slate-200")
    else:
        style = tw("h-px w-full shrink-0 bg-slate-200")
    if decorative:
        attributes = {
            "data-orientation": orientation,
            "data-slot": "separator",
            "role": "none",
        }
    else:
        attributes = {
            "aria-orientation": orientation,
            "data-orientation": orientation,
            "data-slot": "separator",
            "role": "separator",
        }
    return tag("div", style, attributes)
