from pyjs import js
from pyjs.web.dom import document, localStorage, navigator, window
from pyjs.web.domx import CustomElement, button, dialog, div, input, ref, tag
from pyjs.web.events import Event, EventTarget, KeyboardEvent
from pyjs.web.html import HTMLElement
from pyjs.web.javascript import JSON


@js
class DocsEventListener:
    def __init__(self, callback: callable):
        self.callback = callback

    @js(include=True)
    def handleEvent(self, event: Event):
        self.callback(event)


@js
class CodeCopyListener:
    def __init__(self, button_element: HTMLElement, code_element: HTMLElement):
        self.button = button_element
        self.code = code_element

    @js(include=True)
    async def handleEvent(self, event: Event):
        text = self.code.textContent
        if text is None:
            return
        await navigator.clipboard.writeText(text)
        self.button.textContent = "Copied"


@js
def bind(element: EventTarget, event_name: str, callback: callable) -> DocsEventListener:
    listener = DocsEventListener(callback)
    element.addEventListener(event_name, listener)
    return listener


@js
def search_icon():
    return tag(
        "svg",
        {
            "aria-hidden": "true",
            "class": "search-icon",
            "viewBox": "0 0 24 24",
        },
        tag("circle", {"cx": "11", "cy": "11", "r": "7"}),
        tag("path", {"d": "m20 20-3.8-3.8"}),
    )


@js
class DocsApp(CustomElement):
    def __init__(
        self,
        site_name: str = "",
        home_href: str = "./",
        navigation="",
        article="",
        outline="",
        search_data="[]",
        site_home_href: str = "",
        site_navigation="",
    ):
        super().__init__()
        if not site_home_href:
            site_home_href = home_href
        self.menu_button = ref(
            button(
                {
                    "aria-controls": "docs-navigation",
                    "aria-expanded": "false",
                    "aria-label": "Open navigation",
                    "class": "icon-button mobile-menu-button",
                    "type": "button",
                },
                "Menu",
            )
        )
        self.search_button = ref(
            button(
                {
                    "aria-label": "Search documentation",
                    "class": "search-button",
                    "type": "button",
                },
                search_icon(),
                tag("span", {"class": "search-label"}, "Search docs"),
                tag("kbd", "⌘ K"),
            )
        )
        self.theme_button = ref(
            button(
                {
                    "aria-label": "Switch color theme",
                    "class": "icon-button theme-button",
                    "type": "button",
                },
                "Theme",
            )
        )
        self.search_input = ref(
            input(
                {
                    "aria-label": "Search documentation",
                    "autocomplete": "off",
                    "class": "search-input",
                    "placeholder": "Search the documentation…",
                    "type": "search",
                }
            )
        )
        self.search_results = ref(
            div(
                {"aria-live": "polite", "class": "search-results"},
                div({"class": "search-empty"}, "Start typing to search every page."),
            )
        )
        self.search_dialog = ref(
            dialog(
                {"aria-label": "Search documentation", "class": "search-dialog"},
                div(
                    {"class": "search-panel"},
                    div(
                        {"class": "search-field"},
                        search_icon(),
                        self.search_input,
                        button(
                            {
                                "aria-label": "Close search",
                                "class": "search-close",
                                "type": "button",
                            },
                            "Esc",
                        ),
                    ),
                    self.search_results,
                ),
            )
        )
        self.search_data = ref(
            tag(
                "script",
                {"class": "docs-search-data", "type": "application/json"},
                search_data,
            )
        )
        tag(
            self,
            tag(
                "a",
                {"class": "skip-link", "href": "#main-content"},
                "Skip to content",
            ),
            tag(
                "header",
                {"class": "site-header"},
                div(
                    {"class": "header-inner"},
                    self.menu_button,
                    tag(
                        "a",
                        {"class": "brand", "href": site_home_href},
                        tag("span", {"class": "brand-mark", "aria-hidden": "true"}, "Py"),
                        tag("span", site_name),
                    ),
                    tag("a", {"class": "brand-section", "href": home_href}, "Docs"),
                    site_navigation,
                    div({"class": "header-spacer"}),
                    self.search_button,
                    tag(
                        "a",
                        {
                            "aria-label": "View PyJS on GitHub",
                            "class": "icon-button github-button",
                            "href": "https://github.com/pyjs/pyjs",
                        },
                        "GitHub",
                    ),
                    self.theme_button,
                ),
            ),
            div(
                {"class": "docs-layout"},
                tag(
                    "aside",
                    {
                        "aria-label": "Documentation navigation",
                        "class": "docs-sidebar",
                        "id": "docs-navigation",
                    },
                    navigation,
                ),
                tag(
                    "main",
                    {"class": "docs-main", "id": "main-content"},
                    article,
                ),
                tag(
                    "aside",
                    {"aria-label": "On this page", "class": "docs-outline"},
                    outline,
                ),
            ),
            self.search_dialog,
            self.search_data,
        )

    def initialize(self):
        bind(self.menu_button, "click", self.toggle_menu)
        bind(self.search_button, "click", self.open_search)
        bind(self.theme_button, "click", self.toggle_theme)
        bind(self.search_input, "input", self.update_search)
        bind(self.search_dialog.querySelector(".search-close"), "click", self.close_search)
        bind(self.search_dialog, "click", self.handle_dialog_click)
        bind(window, "keydown", self.handle_keyboard)
        self.apply_theme(localStorage.getItem("pyjs-docs-theme"))
        self.add_code_copy_buttons()

    def apply_theme(self, theme: str | None):
        root = document.documentElement
        if root is None:
            return
        if theme == "light" or theme == "dark":
            root.setAttribute("data-theme", theme)
        else:
            root.removeAttribute("data-theme")
        dark = theme == "dark"
        if theme is None:
            dark = window.matchMedia("(prefers-color-scheme: dark)").matches
        self.theme_button.textContent = "Light" if dark else "Dark"
        self.theme_button.setAttribute(
            "aria-label", "Use light theme" if dark else "Use dark theme"
        )

    def toggle_theme(self, event: Event | None = None):
        root = document.documentElement
        if root is None:
            return
        current = root.getAttribute("data-theme")
        if current is None:
            current = (
                "dark" if window.matchMedia("(prefers-color-scheme: dark)").matches else "light"
            )
        theme = "light" if current == "dark" else "dark"
        localStorage.setItem("pyjs-docs-theme", theme)
        self.apply_theme(theme)

    def toggle_menu(self, event: Event | None = None):
        expanded = self.menu_button.getAttribute("aria-expanded") == "true"
        self.menu_button.setAttribute("aria-expanded", "false" if expanded else "true")
        if expanded:
            self.removeAttribute("data-menu-open")
        else:
            self.setAttribute("data-menu-open", "")

    def open_search(self, event: Event | None = None):
        if not self.search_dialog.open:
            self.search_dialog.showModal()
        self.search_input.focus()

    def close_search(self, event: Event | None = None):
        if self.search_dialog.open:
            self.search_dialog.close()

    def handle_keyboard(self, event: KeyboardEvent):
        if (event.metaKey or event.ctrlKey) and event.key.lower() == "k":
            event.preventDefault()
            self.open_search()
        elif event.key == "Escape":
            self.close_search()

    def handle_dialog_click(self, event: Event):
        if event.target is self.search_dialog:
            self.close_search()

    def update_search(self, event: Event | None = None):
        query = self.search_input.value.strip().lower()
        self.search_results.replaceChildren()
        if not query:
            self.search_results.append(
                div({"class": "search-empty"}, "Start typing to search every page.")
            )
            return

        search_data = self.search_data.textContent
        if search_data is None:
            return
        records: list[dict[str, str]] = JSON.parse(search_data)
        matches: list[dict[str, str]] = []
        for record in records:
            searchable = (
                record["title"].lower()
                + " "
                + record["section"].lower()
                + " "
                + record["text"].lower()
            )
            if query in searchable:
                matches.append(record)
            if len(matches) == 12:
                break
        if not matches:
            self.search_results.append(div({"class": "search-empty"}, f"No results for “{query}”."))
            return
        for record in matches:
            self.search_results.append(
                tag(
                    "a",
                    {"class": "search-result", "href": record["url"]},
                    tag("span", {"class": "search-result-title"}, record["title"]),
                    tag("span", {"class": "search-result-section"}, record["section"]),
                    tag("span", {"class": "search-result-text"}, record["text"]),
                )
            )

    def add_code_copy_buttons(self):
        for block in self.querySelectorAll(".highlight"):
            code = block.querySelector("code")
            if code is not None:
                copy_button = button({"class": "copy-button", "type": "button"}, "Copy")
                copy_button.addEventListener("click", CodeCopyListener(copy_button, code))
                block.append(copy_button)


@js
def main(
    site_name: str = "PyJS",
    home_href: str = "./",
    navigation="",
    article="",
    outline="",
    search_data="[]",
    site_home_href: str = "",
    site_navigation="",
):
    return DocsApp(
        site_name,
        home_href,
        navigation,
        article,
        outline,
        search_data,
        site_home_href,
        site_navigation,
    )
