from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Label(*children):
    return tag(
        "label",
        tw(
            "flex select-none items-center gap-2 text-sm font-medium leading-none text-slate-950"
        ),
        {"data-slot": "label"},
        *children,
    )
