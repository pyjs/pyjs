from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Table(*children):
    return tag(
        "div",
        tw("relative w-full overflow-x-auto"),
        {"data-slot": "table-container"},
        tag(
            "table",
            tw("w-full caption-bottom text-sm"),
            {"data-slot": "table"},
            *children,
        ),
    )


@js
def TableHeader(*children):
    return tag(
        "thead",
        tw("border-b border-slate-200"),
        {"data-slot": "table-header"},
        *children,
    )


@js
def TableBody(*children):
    return tag("tbody", {"data-slot": "table-body"}, *children)


@js
def TableFooter(*children):
    return tag(
        "tfoot",
        tw("border-t border-slate-200 bg-slate-50 font-medium"),
        {"data-slot": "table-footer"},
        *children,
    )


@js
def TableRow(*children):
    return tag(
        "tr",
        tw("border-b border-slate-200 transition-colors hover:bg-slate-50"),
        {"data-slot": "table-row"},
        *children,
    )


@js
def TableHead(*children):
    return tag(
        "th",
        tw(
            "h-10 whitespace-nowrap px-2 text-left align-middle font-medium text-slate-700"
        ),
        {"data-slot": "table-head", "scope": "col"},
        *children,
    )


@js
def TableCell(*children):
    return tag(
        "td",
        tw("whitespace-nowrap p-2 align-middle text-slate-700"),
        {"data-slot": "table-cell"},
        *children,
    )


@js
def TableCaption(*children):
    return tag(
        "caption",
        tw("mt-4 text-sm text-slate-500"),
        {"data-slot": "table-caption"},
        *children,
    )
