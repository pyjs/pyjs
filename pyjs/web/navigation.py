from pyjs import JS, js
from pyjs.web.dom import AbortController, Element, document, location, window
from pyjs.web.domx import CustomElement, ref, tag
from pyjs.web.events import Event, MouseEvent
from pyjs.web.html import DOMParser, HTMLElement
from pyjs.web.network import Headers, fetch
from pyjs.web.url import URL

NAVIGATION_HEADER: JS[str] = "X-PyJS-Navigation"
PAGE_SELECTOR: JS[str] = "[data-pyjs-page]"


@js
def navigation_page(content: Element, layout_id: str) -> HTMLElement:
    return tag(
        "div",
        {
            "data-pyjs-layout": layout_id,
            "data-pyjs-page": "",
        },
        content,
    )


@js
def clicked_link(event: MouseEvent, root: Element) -> Element | None:
    target = event.target
    if isinstance(target, Element):
        link = target.closest("a[href]")
        if link is not None and root.contains(link):
            return link
    return None


@js
class PageOutlet(CustomElement):
    def __init__(self, content: Element, layout_id: str = "main"):
        super().__init__()
        self.set_data("layout", layout_id)
        self.setAttribute("aria-live", "polite")
        self.add(navigation_page(content, layout_id))

    def add(self, *children):
        tag(self, *children)


@js
class NavigationLayout(CustomElement):
    def __init__(self, content: Element, layout_id: str = "main"):
        super().__init__()
        self.outlet = ref(PageOutlet(content, layout_id))
        self.controller: AbortController | None = None

    def add(self, *children):
        tag(self, *children)

    def initialize(self):
        self.controller = None
        self.addEventListener("click", self.link_clicked)
        window.addEventListener("popstate", self.history_changed)
        self.update_current_link(location.href)

    def link_clicked(self, event: MouseEvent):
        if event.defaultPrevented or event.button != 0:
            return
        if event.altKey or event.ctrlKey or event.metaKey or event.shiftKey:
            return

        link = clicked_link(event, self)
        if link is None:
            return
        if link.getAttribute("download") is not None:
            return
        link_target = link.getAttribute("target")
        if link_target is not None and link_target != "" and link_target != "_self":
            return
        if link.getAttribute("data-pyjs-navigation") == "false":
            return

        href = link.getAttribute("href")
        if href is None or href == "":
            return
        url = URL(href, location.href)
        if url.origin != location.origin:
            return
        if (
            url.pathname == location.pathname
            and url.search == location.search
            and url.hash != ""
        ):
            return

        event.preventDefault()
        self.navigate(url.href, True)

    def history_changed(self, event: Event):
        self.navigate(location.href, False)

    async def navigate(self, href: str, push_history: bool = True):
        if self.controller is not None:
            self.controller.abort()
        controller = AbortController()
        self.controller = controller
        self.outlet.setAttribute("aria-busy", "true")
        self.dispatchEvent(Event("pyjs:navigation-start", bubbles=True))

        headers = Headers()
        headers.set(NAVIGATION_HEADER, "1")
        try:
            response = await fetch(
                href,
                {
                    "headers": headers,
                    "signal": controller.signal,
                },
            )
            target_url = response.url if response.url != "" else href
            if not response.ok:
                location.assign(target_url)
                return

            source = await response.text()
            parsed = DOMParser().parseFromString(source, "text/html")
            next_page = parsed.querySelector(PAGE_SELECTOR)
            if next_page is None:
                location.assign(target_url)
                return
            next_layout = next_page.getAttribute("data-pyjs-layout")
            current_layout = self.outlet.get_data("layout")
            if next_layout is None or current_layout is None:
                location.assign(target_url)
                return
            if next_layout != current_layout:
                location.assign(target_url)
                return

            self.outlet.replaceChildren(next_page)
            next_title = parsed.querySelector("title")
            current_title = document.querySelector("title")
            if next_title is not None and current_title is not None:
                current_title.textContent = next_title.textContent
            self.update_current_link(target_url)
            if push_history:
                window.history.pushState(None, "", target_url)
                window.scrollTo(top=0, left=0)

            heading = next_page.querySelector("h1")
            if isinstance(heading, HTMLElement):
                heading.setAttribute("tabindex", "-1")
                heading.focus(preventScroll=True)
            self.dispatchEvent(Event("pyjs:navigation-end", bubbles=True))
        except Exception:
            if not controller.signal.aborted:
                self.dispatchEvent(Event("pyjs:navigation-error", bubbles=True))
                location.assign(href)
        finally:
            if self.controller is controller:
                self.controller = None
                self.outlet.removeAttribute("aria-busy")

    def update_current_link(self, href: str):
        current = URL(href, location.href)
        for link in self.querySelectorAll("a[data-pyjs-navigation-link][href]"):
            link_href = link.getAttribute("href")
            if link_href is None:
                continue
            destination = URL(link_href, location.href)
            if (
                destination.origin == current.origin
                and destination.pathname == current.pathname
                and destination.search == current.search
            ):
                link.setAttribute("aria-current", "page")
            else:
                link.removeAttribute("aria-current")
