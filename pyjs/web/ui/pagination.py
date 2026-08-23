from collections.abc import Awaitable, Callable

from pyjs import js
from pyjs.server import CursorPageRequest, Page
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, a, div, require_element, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui.button import Button

type _PageCallback = Callable[[CursorPageRequest], Awaitable[object]]


@js
class CursorPagination(ProxyElement):
    def __init__(
        self,
        previous_cursor: str | None = None,
        next_cursor: str | None = None,
        *,
        label: str = "Pagination",
        size: int = 25,
    ):
        if size < 1:
            raise ValueError("Pagination size must be positive.")
        self.size = size
        self._page_callback: _PageCallback | None = None
        self.previous = Button("Previous", variant="outline")
        self.next = Button("Next", variant="outline")
        self.previous.setAttribute("data-direction", "previous")
        self.next.setAttribute("data-direction", "next")
        self.set_cursor(self.previous, previous_cursor)
        self.set_cursor(self.next, next_cursor)
        self.element = tag(
            "nav",
            {
                "aria-label": label,
                "data-page-size": str(size),
                "data-slot": "cursor-pagination",
            },
            div(tw("flex items-center gap-2"), self.previous, self.next),
        )

    def _hydrate(self, element: Element):
        super()._hydrate(element)
        size = element.getAttribute("data-page-size")
        if size is None:
            raise ValueError("Cursor pagination is missing its page size.")
        self.size = int(size)
        self.previous = Button()
        self.previous._hydrate(
            require_element(element, '[data-direction="previous"]')
        )
        self.next = Button()
        self.next._hydrate(require_element(element, '[data-direction="next"]'))
        return self

    def set_page[Value](self, page: Page[Value]):
        self.set_cursor(self.previous, page.previous)
        self.set_cursor(self.next, page.next)

    def set_size(self, size: int):
        if size < 1:
            raise ValueError("Pagination size must be positive.")
        self.size = size
        self.element.setAttribute("data-page-size", str(size))

    def set_cursor(self, button: Button, cursor: str | None):
        if cursor is None:
            button.removeAttribute("data-cursor")
            button.setAttribute("disabled", "")
        else:
            button.setAttribute("data-cursor", cursor)
            button.removeAttribute("disabled")

    def previous_request(self) -> CursorPageRequest | None:
        cursor = self.previous.getAttribute("data-cursor")
        if cursor is None:
            return None
        return CursorPageRequest(size=self.size, before=cursor)

    def next_request(self) -> CursorPageRequest | None:
        cursor = self.next.getAttribute("data-cursor")
        if cursor is None:
            return None
        return CursorPageRequest(size=self.size, after=cursor)

    def on_previous(self, callback: callable):
        self.previous.on_click(callback)

    def on_next(self, callback: callable):
        self.next.on_click(callback)

    def on_page(
        self,
        callback: _PageCallback,
    ):
        self._page_callback = callback
        self.on_previous(self._load_previous)
        self.on_next(self._load_next)

    async def _load_previous(self, event: Event):
        callback = self._page_callback
        request = self.previous_request()
        if callback is not None and request is not None:
            await callback(request)

    async def _load_next(self, event: Event):
        callback = self._page_callback
        request = self.next_request()
        if callback is not None and request is not None:
            await callback(request)


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
