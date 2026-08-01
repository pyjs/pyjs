from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Spinner(label: str = "Loading"):
    return tag(
        "span",
        tw(
            "inline-block size-4 animate-spin rounded-full border-2 border-slate-300 "
            "border-t-slate-950"
        ),
        {"aria-label": label, "data-slot": "spinner", "role": "status"},
    )
