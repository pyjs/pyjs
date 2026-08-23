from collections.abc import Awaitable, Callable

from pyjs import js
from pyjs.server import CursorPageRequest
from pyjs.web.dom import (
    IntersectionObserver,
    IntersectionObserverEntry,
    IntersectionObserverInit,
)
from pyjs.web.domx import div, p, ref, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget
from pyjs.web.ui.button import Button

type _LoadCallback = Callable[[CursorPageRequest], Awaitable[object]]


@js
class InfiniteScroll(Widget):
    observer: IntersectionObserver | None
    _load_callback: _LoadCallback | None
    _loading: bool

    def __init__(
        self,
        next_cursor: str | None = None,
        *,
        label: str = "Load more",
        root_margin: str = "240px 0px",
        size: int = 25,
    ):
        super().__init__()
        if size < 1:
            raise ValueError("Infinite-scroll page size must be positive.")
        self.set_data("page-size", str(size))
        self.set_data("root-margin", root_margin)
        self.button = ref(Button(label, variant="outline"))
        self.button.setAttribute("data-slot", "infinite-scroll-button")
        self.status = ref(
            p(
                tw("text-sm text-slate-500"),
                {
                    "aria-live": "polite",
                    "data-slot": "infinite-scroll-status",
                },
            )
        )
        self.sentinel = ref(
            div(
                tw("h-px w-full"),
                {
                    "aria-hidden": "true",
                    "data-slot": "infinite-scroll-sentinel",
                },
            )
        )
        self.add(
            tw("grid justify-items-center gap-3 py-5"),
            {
                "aria-busy": "false",
                "data-slot": "infinite-scroll",
            },
            self.button,
            self.status,
            self.sentinel,
        )
        self.set_cursor(next_cursor)

    def initialize(self):
        self._loading = False
        self.observer = None
        self.start_observing()

    def reconnected(self):
        self.start_observing()

    def disconnected(self):
        if self.observer is not None:
            self.observer.disconnect()
            self.observer = None

    def on_load(self, callback: _LoadCallback):
        self._load_callback = callback
        self.button.on_click(self.load_more)

    def set_cursor(self, cursor: str | None):
        if cursor is None:
            self.removeAttribute("data-cursor")
            self.button.setAttribute("disabled", "")
            self.status.textContent = "All results loaded."
        else:
            self.set_data("cursor", cursor)
            if not self._is_loading():
                self.button.removeAttribute("disabled")
            self.status.textContent = ""

    def next_request(self) -> CursorPageRequest | None:
        cursor = self.get_data("cursor")
        size = self.get_data("page-size")
        if cursor is None or size is None:
            return None
        return CursorPageRequest(size=int(size), after=cursor)

    def start_observing(self):
        if self.observer is not None or self.get_data("cursor") is None:
            return
        root_margin = self.get_data("root-margin")
        if root_margin is None:
            root_margin = "0px"
        observer = IntersectionObserver(
            self.intersected,
            IntersectionObserverInit(rootMargin=root_margin),
        )
        observer.observe(self.sentinel)
        self.observer = observer

    def restart_observing(self):
        if self.observer is not None:
            self.observer.disconnect()
            self.observer = None
        self.start_observing()

    def intersected(
        self,
        entries: list[IntersectionObserverEntry],
        observer: IntersectionObserver,
    ):
        for entry in entries:
            if entry.isIntersecting:
                self.button.element.click()
                return

    def _is_loading(self) -> bool:
        return self.getAttribute("aria-busy") == "true"

    async def load_more(self, event: Event):
        callback = self._load_callback
        request = self.next_request()
        if self._loading or callback is None or request is None:
            return
        self._loading = True
        self.setAttribute("aria-busy", "true")
        self.button.setAttribute("disabled", "")
        self.status.textContent = "Loading more results…"
        try:
            await callback(request)
        except Exception:
            self.status.textContent = "Could not load more results. Try again."
        finally:
            self._loading = False
            self.setAttribute("aria-busy", "false")
            if self.get_data("cursor") is not None:
                self.button.removeAttribute("disabled")
            self.restart_observing()
