from pyjs import js, nojs
from pyjs.server import NavigationPage
from pyjs.web.dom import Element
from pyjs.web.domx import a, div, span, tag, tw
from pyjs.web.navigation import NavigationLayout

from .catalog import CatalogApp
from .workspace import WorkspaceApp


@js
def navigation_link(path: str, label: str):
    return a(
        tw(
            "rounded-md px-3 py-2 text-sm font-medium text-slate-600 "
            "hover:bg-slate-100 hover:text-slate-950 "
            "aria-[current=page]:bg-slate-950 aria-[current=page]:text-white"
        ),
        {
            "data-pyjs-navigation-link": "",
            "href": path,
        },
        label,
    )


@js
class ComponentsApp(NavigationLayout):
    def __init__(self, content: Element, layout_id: str = "components"):
        super().__init__(content, layout_id)
        self.add(
            tw("block min-h-screen bg-slate-50 text-slate-950"),
            tag(
                "header",
                tw(
                    "sticky top-0 z-50 border-b border-slate-200 bg-white/95 "
                    "backdrop-blur"
                ),
                div(
                    tw(
                        "mx-auto flex h-16 max-w-7xl items-center gap-5 px-5 "
                        "lg:px-8"
                    ),
                    a(
                        tw("flex items-center gap-2 font-semibold tracking-tight"),
                        {"href": "/"},
                        span(
                            tw(
                                "flex size-8 items-center justify-center rounded-lg "
                                "bg-slate-950 text-sm text-white"
                            ),
                            "Py",
                        ),
                        "Components",
                    ),
                    tag(
                        "nav",
                        tw("ml-auto flex items-center gap-1"),
                        {"aria-label": "Component example pages"},
                        navigation_link("/", "Catalog"),
                        navigation_link("/workspace", "Workspace block"),
                    ),
                ),
            ),
            self.outlet,
        )


@js
def catalog_view() -> Element:
    return CatalogApp()


@js
def workspace_view() -> Element:
    return WorkspaceApp()


@nojs
def layout(request, content: Element, layout_id: str):
    return ComponentsApp(content, layout_id)


@nojs
def catalog_page(request):
    return NavigationPage(catalog_view(), "Components · PyJS")


@nojs
def workspace_page(request):
    return NavigationPage(workspace_view(), "Workspace block · Components · PyJS")


def main():
    return ComponentsApp(catalog_view())
