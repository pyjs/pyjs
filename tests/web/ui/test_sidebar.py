import pytest

from pyjs.javascript.transpiler import bundle
from pyjs.web.domx import tw
from pyjs.web.ui.sidebar import MobileSidebar, SidebarContent


def mobile_sidebar_entrypoint():
    return MobileSidebar("Navigation", SidebarContent("Links"))


@pytest.mark.pyjs_python
def test_mobile_sidebar_styles_can_replace_each_component_surface():
    sidebar = MobileSidebar(
        "Navigation",
        SidebarContent("Links"),
        trigger_style=tw("size-10 lg:hidden"),
        content_style=tw("fixed w-80"),
        surface_style=tw("flex h-full"),
    )

    assert sidebar.trigger.getAttribute("class") == "size-10 lg:hidden"
    assert sidebar.content.dialog_element.getAttribute("class") == "fixed w-80"
    assert sidebar.content.surface.getAttribute("class") == "flex h-full"


@pytest.mark.pyjs_python
def test_mobile_sidebar_bundle_contains_its_responsive_visibility_rule():
    _, css = bundle(mobile_sidebar_entrypoint, include_css=True)

    assert ".md\\:hidden" in css
