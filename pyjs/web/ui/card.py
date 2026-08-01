from pyjs import js
from pyjs.web.domx import div, tw


@js
def Card(*args):
    return div(
        tw(
            "flex flex-col gap-6 rounded-xl border border-slate-200 bg-white py-6 shadow-sm"
        ),
        {"data-size": "default", "data-slot": "card"},
        *args,
    )


@js
def CardHeader(*args):
    return div(
        tw(
            "grid auto-rows-min grid-rows-[auto_auto] items-start gap-1.5 px-6 "
            "has-data-[slot=card-action]:grid-cols-[1fr_auto]"
        ),
        {"data-slot": "card-header"},
        *args,
    )


@js
def CardTitle(*args):
    return div(
        tw("font-semibold leading-none text-slate-950"),
        {"data-slot": "card-title"},
        *args,
    )


@js
def CardDescription(*args):
    return div(tw("text-sm text-slate-500"), {"data-slot": "card-description"}, *args)


@js
def CardAction(*args):
    return div(
        tw("col-start-2 row-span-2 row-start-1 self-start justify-self-end"),
        {"data-slot": "card-action"},
        *args,
    )


@js
def CardContent(*args):
    return div(tw("px-6 text-sm text-slate-700"), {"data-slot": "card-content"}, *args)


@js
def CardFooter(*args):
    return div(tw("flex items-center gap-2 px-6"), {"data-slot": "card-footer"}, *args)
