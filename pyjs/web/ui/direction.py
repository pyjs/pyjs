from pyjs import js
from pyjs.web.domx import div


@js
def Direction(*children, direction: str = "ltr"):
    if direction != "ltr" and direction != "rtl":
        raise ValueError("Direction must be ltr or rtl")
    return div({"data-slot": "direction", "dir": direction}, *children)
