from pyjs import js
from pyjs.web.domx import tag, tw


@js
def Breadcrumb(*children):
    return tag(
        "nav",
        {"aria-label": "Breadcrumb", "data-slot": "breadcrumb"},
        *children,
    )


@js
def BreadcrumbList(*children):
    return tag(
        "ol",
        tw("flex flex-wrap items-center gap-1.5 text-sm text-slate-500 sm:gap-2.5"),
        {"data-slot": "breadcrumb-list"},
        *children,
    )


@js
def BreadcrumbItem(*children):
    return tag(
        "li",
        tw("inline-flex items-center gap-1.5"),
        {"data-slot": "breadcrumb-item"},
        *children,
    )


@js
def BreadcrumbLink(href: str, *children):
    return tag(
        "a",
        tw("transition-colors hover:text-slate-950"),
        {"data-slot": "breadcrumb-link", "href": href},
        *children,
    )


@js
def BreadcrumbPage(*children):
    return tag(
        "span",
        tw("font-normal text-slate-950"),
        {
            "aria-current": "page",
            "aria-disabled": "true",
            "data-slot": "breadcrumb-page",
            "role": "link",
        },
        *children,
    )


@js
def BreadcrumbSeparator(symbol: str = "›"):
    return tag(
        "li",
        tw("text-slate-400"),
        {
            "aria-hidden": "true",
            "data-slot": "breadcrumb-separator",
            "role": "presentation",
        },
        symbol,
    )


@js
def BreadcrumbEllipsis():
    return tag(
        "span",
        tw("flex size-9 items-center justify-center text-slate-500"),
        {
            "aria-hidden": "true",
            "data-slot": "breadcrumb-ellipsis",
            "role": "presentation",
        },
        "…",
        tag("span", tw("sr-only"), "More"),
    )
