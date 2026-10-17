from typing import cast

import pytest

from pyjs import js
from pyjs.testing.helpers import at
from pyjs.web.dom import DOMException, DOMTokenList
from pyjs.web.domx import ProxyElement, div, ref, tag
from pyjs.web.events import Event
from pyjs.web.html import HTMLSelectElement


@js
class ForwardedBox(ProxyElement):
    def __init__(self):
        self.element = div("proxy child")


@js
class DeferredBox(ProxyElement):
    pass


@pytest.mark.pyjs_web
@js
def test_proxy_without_initializer_can_be_created_before_hydration():
    box = ref(DeferredBox())
    assert isinstance(box, DeferredBox)
    element = div("hydrated")
    assert box._hydrate(element) is box
    box.setAttribute("data-value", "kept")
    root = div(box)
    assert root.firstChild is element
    assert box.getAttribute("data-value") == "kept"


def test_select_tag_uses_its_concrete_cpython_defaults():
    control = tag("select")
    assert isinstance(control, HTMLSelectElement)
    assert control.nodeName == "SELECT"
    assert control.value == ""


@js
def _select_changed(event: Event) -> None:
    control = cast(HTMLSelectElement, event.target)
    control.setAttribute("data-fired", "yes")


@pytest.mark.pyjs_web
@js
def test_select_tag_and_listener_remain_browser_operations():
    control = cast(HTMLSelectElement, tag("select"))
    assert isinstance(control, HTMLSelectElement)
    assert control.value == ""
    control.addEventListener("change", _select_changed, once=True)
    control.dispatchEvent(Event("change"))
    assert control.getAttribute("data-fired") == "yes"


@pytest.mark.pyjs_web
@js
def test_proxy_field_annotation_preserves_forwarding_and_child_identity():
    box = ForwardedBox()
    box.setAttribute("data-value", "one")
    root = div(box)
    assert root.firstChild is box.element
    assert box.getAttribute("data-value") == "one"
    box.removeAttribute("data-value")
    assert box.getAttribute("data-value") is None
    replacement = div("replacement")
    assert box._hydrate(replacement) is box
    assert box.element is replacement


def test_insert_before_rejects_a_reference_outside_the_parent():
    parent = div()
    reference = div("ref")
    node = div("moved")
    other = div(reference, node)

    try:
        parent.insertBefore(node, reference)
    except DOMException as error:
        assert error.name == "NotFoundError"
        assert error.code == DOMException.NOT_FOUND_ERR
    else:
        raise AssertionError("insertBefore accepted a foreign reference node")
    assert node.parentNode is other
    assert reference.parentNode is other

    parent.append(reference)
    parent.insertBefore(node, reference)
    assert list(parent.children) == [node, reference]


def test_dom_token_list_matches_idempotent_browser_mutations_in_python():
    tokens = DOMTokenList()

    tokens.add("hidden", "hidden")
    tokens.remove("missing")

    assert tokens.tokens == ["hidden"]
    assert tokens.length == 1
    assert tokens.value == "hidden"
    assert tokens.contains("hidden")
    assert tokens.toggle("hidden") is False
    assert tokens.toggle("visible") is True
    assert tokens.replace("visible", "grid") is True
    assert tokens.replace("missing", "block") is False
    assert tokens.item(0) == "grid"
    assert tokens.item(1) is None

    tokens.add("block")
    assert tokens.replace("grid", "block") is True
    assert tokens.tokens == ["block"]
    assert tokens.replace("block", "block") is True
    assert tokens.tokens == ["block"]
    assert tokens.length == 1
    assert tokens.value == "block"


def test_native_html_views_keep_their_browser_property_types():
    at(
        """
        from pyjs.web.html import HTMLElement

        def main():
            element = HTMLElement()
            element.className = "panel"
            element.classList.add("active")
            element.dataset["state"] = "open"
            names = list(element.dataset)
            entries = list(element.dataset.items())
            dataset_length = len(element.dataset)
            count = element.children.length
        """,
        """
        def main() -> None:
            element: HTMLElement = HTMLElement()
            element.className = 'panel'
            element.classList.[DOMTokenList]add('active')
            element.dataset.[DOMStringMap]__setitem__!('state', 'open')
            names: list[str] = list__str(element.dataset)
            entries: list[tuple[str, str]] = list__tuple__str_str(element.dataset.[DOMStringMap]items!())
            dataset_length: int = element.dataset.[DOMStringMap]__len__!()
            count: int = element.children.length
        """,
        """
        export function main() {
            var element = new HTMLElement();
            element.className = 'panel';
            element.classList.add('active');
            element.dataset['state'] = 'open';
            var names = Array.from(Object.keys(element.dataset)[Symbol.iterator]());
            var entries = Array.from(Object.entries(element.dataset));
            var dataset_length = Object.keys(element.dataset).length;
            var count = element.children.length;
        }
        """,
    )


@pytest.mark.pyjs_web
@js
def test_insert_before_rejects_a_foreign_reference_in_the_browser():
    parent = div()
    reference = div("ref")
    node = div("moved")
    other = div(reference, node)
    caught = False
    try:
        parent.insertBefore(node, reference)
    except Exception:
        caught = True
    assert caught
    assert node.parentNode is other
    parent.append(reference)
    parent.insertBefore(node, reference)
    assert node.parentNode is parent
    assert node.nextElementSibling is reference


@pytest.mark.pyjs_web
@js
def test_dataset_iteration_uses_its_browser_keys():
    element = div()
    element.dataset["userId"] = "42"
    element.dataset["releaseChannel"] = "stable"

    assert list(element.dataset) == ["userId", "releaseChannel"]
    assert list(element.dataset.items()) == [
        ("userId", "42"),
        ("releaseChannel", "stable"),
    ]
    assert len(element.dataset) == 2


def test_domrect_field_on_method_call_result():
    at(
        """
        from pyjs.web.html import HTMLElement

        def main():
            element = HTMLElement()
            left = element.getBoundingClientRect().left
        """,
        """
        def main() -> None:
            element: HTMLElement = HTMLElement()
            left: float = element.[HTMLElement]getBoundingClientRect().left
        """,
        """
        export function main() {
            var element = new HTMLElement();
            var left = element.getBoundingClientRect().left;
        }
        """,
    )


def test_resize_observer_accepts_bound_callback_and_element():
    at(
        """
        from pyjs import js
        from pyjs.web.dom import ResizeObserver, ResizeObserverEntry
        from pyjs.web.html import HTMLElement

        @js
        class Listener:
            def resized(
                self,
                entries: list[ResizeObserverEntry],
                observer: ResizeObserver,
            ):
                observer.disconnect()

        def main():
            element = HTMLElement()
            listener = Listener()
            observer = ResizeObserver(listener.resized)
            observer.observe(element, box="device-pixel-content-box")
            observer.unobserve(element)
        """,
        """
        class Listener:

            def resized(entries: list__ResizeObserverEntry, observer: ResizeObserver) -> None:
                observer.[ResizeObserver]disconnect()

        def main() -> None:
            element: HTMLElement = HTMLElement()
            listener: Listener = Listener()
            observer: ResizeObserver = ResizeObserver(listener.[Listener]resized)
            observer.[ResizeObserver]observe(element, box='device-pixel-content-box')
            observer.[ResizeObserver]unobserve(element)
        """,
        """
        export class Listener {

            resized(entries, observer) {
                observer.disconnect();
            }
        }

        export function main() {
            var element = new HTMLElement();
            var listener = new Listener();
            var observer = new ResizeObserver(listener.resized.bind(listener));
            observer.observe(element, {box: 'device-pixel-content-box'});
            observer.unobserve(element);
        }
        """,
    )
