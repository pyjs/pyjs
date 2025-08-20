from pyjs import js
from pyjs.domx import div, tw


@js
def Card(*args):
    return div(tw("bg-card text-card-foreground flex flex-col gap-6 rounded-xl border py-6 shadow-sm"), *args)


@js
def CardHeader(*args):
    return div(tw("@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-1.5 px-6 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6"), *args)


@js
def CardTitle(*args):
    return div(tw("leading-none font-semibold"), *args)


@js
def CardDescription(*args):
    return div(tw("text-muted-foreground text-sm"), *args)


@js
def CardAction(*args):
    return div(tw("col-start-2 row-span-2 row-start-1 self-start justify-self-end"), *args)


@js
def CardContent(*args):
    return div(tw("px-6"), *args)


@js
def CardFooter(*args):
    return div(tw("flex items-center px-6 [.border-t]:pt-6"), *args)
