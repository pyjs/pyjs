from pyjs import js
from pyjs.web.domx import a, tag, tw


@js
def Pagination(*children, label: str = "Pagination"):
    return tag("nav", {"aria-label": label, "data-slot": "pagination"}, *children)


@js
def PaginationContent(*children):
    return tag(
        "ul",
        tw("flex items-center gap-1"),
        {"data-slot": "pagination-content"},
        *children,
    )


@js
def PaginationItem(*children):
    return tag("li", {"data-slot": "pagination-item"}, *children)


@js
def PaginationLink(href: str, *children, current: bool = False, label: str = ""):
    attributes = {
        "aria-label": label,
        "data-slot": "pagination-link",
        "href": href,
    }
    if current:
        attributes["aria-current"] = "page"
    return a(
        tw(
            "inline-flex h-9 min-w-9 items-center justify-center whitespace-nowrap rounded-md "
            "px-2 text-sm hover:bg-slate-100 "
            "aria-[current=page]:border aria-[current=page]:border-slate-300 "
            "aria-[current=page]:bg-white"
        ),
        attributes,
        *children,
    )


@js
def PaginationPrevious(href: str, label: str = "Go to previous page"):
    return PaginationLink(href, "‹ Previous", label=label)


@js
def PaginationNext(href: str, label: str = "Go to next page"):
    return PaginationLink(href, "Next ›", label=label)


@js
def PaginationEllipsis(label: str = "More pages"):
    return tag(
        "span",
        tw("inline-flex size-9 items-center justify-center text-slate-500"),
        {"aria-label": label, "data-slot": "pagination-ellipsis"},
        "…",
    )
