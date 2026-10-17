import asyncio
import gc
import inspect
import time
import weakref
from datetime import datetime
from typing import get_type_hints

import pytest

from pyjs.javascript import (
    JSON,
    Date,
    JSONObject,
    Math,
    SharedArrayBuffer,
    encodeURIComponent,
)
from pyjs.web.clipboard import (
    Clipboard,
    ClipboardEvent,
    ClipboardItem,
)
from pyjs.web.clipboard import (
    navigator as clipboard_navigator,
)
from pyjs.web.crypto import Crypto, CryptoKey, SubtleCrypto, crypto
from pyjs.web.dom import (
    Attr,
    CDATASection,
    CSSStyleProperties,
    Document,
    DocumentFragment,
    DocumentType,
    DOMRect,
    DOMTokenList,
    Element,
    HTMLCollection,
    IntersectionObserver,
    IntersectionObserverEntry,
    IntersectionObserverInit,
    NamedNodeMap,
    Node,
    NodeList,
    Range,
    Text,
    document,
    window,
)
from pyjs.web.domx import tag, tw
from pyjs.web.dragdrop import DataTransfer, DragEvent
from pyjs.web.encoding import TextDecoder, TextEncoder
from pyjs.web.events import (
    CustomEvent,
    Event,
    EventTarget,
    KeyboardEvent,
    MessageEvent,
    PointerEvent,
    ProgressEvent,
    WheelEvent,
)
from pyjs.web.files import Blob, File, FileList
from pyjs.web.html import (
    DOMStringMap,
    HTMLCanvasElement,
    HTMLDivElement,
    HTMLElement,
    HTMLElementMetaclass,
)
from pyjs.web.indexeddb import IDBDatabase, IDBRequest, indexedDB
from pyjs.web.network import FormData, Headers, Response, WebSocket, XMLHttpRequest
from pyjs.web.serviceworker import (
    Cache,
    CacheStorage,
    Clients,
    FetchEvent,
    Notification,
    PushManager,
    ServiceWorker,
    ServiceWorkerGlobalScope,
    ServiceWorkerRegistration,
    caches,
    navigator,
    service_worker_scope,
)
from pyjs.web.storage import StorageEstimate, StorageManager
from pyjs.web.storage import navigator as storage_navigator
from pyjs.web.svg import SVGElement, SVGLineElement, SVGSVGElement
from pyjs.web.url import URL, URLSearchParams


def test_event_constructors_retain_cpython_values():
    assert Event("ready", bubbles=True).type == "ready"
    assert CustomEvent("change", detail={"value": 3}).detail == {"value": 3}
    assert KeyboardEvent("keydown", key="Enter").key == "Enter"
    assert MessageEvent("message", data="hello").data == "hello"
    assert MessageEvent("message").ports == []

    pointer = PointerEvent("pointerdown", clientX=12, clientY=34)
    assert (pointer.clientX, pointer.clientY) == (12, 34)

    wheel = WheelEvent("wheel", deltaX=5, deltaY=-10)
    assert (wheel.type, wheel.deltaX, wheel.deltaY) == ("wheel", 5, -10)

    progress = ProgressEvent("progress", loaded=3, total=10)
    assert (progress.type, progress.loaded, progress.total) == ("progress", 3, 10)

    transfer = DataTransfer()
    drag = DragEvent("dragstart", clientX=12, clientY=34, dataTransfer=transfer)
    assert drag.dataTransfer is transfer
    assert (drag.clientX, drag.clientY) == (12, 34)


def test_html_classes_retain_cpython_helpers():
    dataset = DOMStringMap()
    dataset["state"] = "open"
    assert dataset["state"] == "open"

    assert HTMLDivElement().tagName == "DIV"
    assert (HTMLCanvasElement().width, HTMLCanvasElement().height) == (300, 150)


def test_generated_html_defaults_are_sparse_and_readable_for_every_element():
    import pyjs.web.html as html

    canvas = HTMLCanvasElement()
    assert vars(canvas) == {}
    assert canvas.width == 300
    assert vars(canvas) == {}

    canvas.width = 640
    assert vars(canvas) == {"width": 640}
    assert HTMLCanvasElement().width == 300

    classes = [
        value
        for value in vars(html).values()
        if inspect.isclass(value)
        and value.__module__ == html.__name__
        and issubclass(value, HTMLElement)
    ]
    for element_class in classes:
        element = element_class()
        for name in element_class.dom_defaults:
            getattr(element, name)


def test_application_html_initializer_can_chain_to_generated_superclass():
    class ApplicationDiv(HTMLDivElement):
        def __init__(self):
            super().__init__()
            self.status = "ready"

    element = ApplicationDiv()

    assert element.status == "ready"
    assert list(element.dataset) == []
    assert element.classList.length == 0


def test_compact_defaults_do_not_retain_application_element_classes():
    class TemporaryElement(HTMLElement):
        pass

    element = TemporaryElement()
    assert element.lang == ""
    reference = weakref.ref(TemporaryElement)

    del element
    del TemporaryElement
    gc.collect()

    assert reference() is None


def test_compact_child_does_not_retain_an_unreachable_parent_tree():
    parent = HTMLDivElement()
    child = HTMLDivElement()
    parent.append("Status", child)
    text = parent.childNodes[0]
    parent_reference = weakref.ref(parent)

    del parent
    gc.collect()

    assert parent_reference() is None
    assert text.parentNode is None
    assert child.parentNode is None


def test_compact_dom_properties_retain_their_public_return_types():
    properties = {
        Element.attributes: NamedNodeMap[Attr],
        Element.childNodes: NodeList[Node],
        Element.children: HTMLCollection[Element],
        Element.classList: DOMTokenList,
        Element.style: CSSStyleProperties,
        HTMLElement.dataset: DOMStringMap,
    }

    for descriptor, return_type in properties.items():
        assert get_type_hints(descriptor.fget)["return"] == return_type


def test_unknown_html_tags_share_one_generic_type_without_growing_the_cache():
    cached_types = len(HTMLElementMetaclass._element_types)

    elements = [document.createElement(f"tenant-widget-{index}") for index in range(100)]

    assert all(type(element) is HTMLElement for element in elements)
    assert elements[0].tagName == "TENANT-WIDGET-0"
    assert elements[-1].tagName == "TENANT-WIDGET-99"
    assert len(HTMLElementMetaclass._element_types) == cached_types


def test_html_collection_views_remain_live_with_mixed_child_nodes():
    parent = HTMLDivElement()
    elements = parent.children
    nodes = parent.childNodes
    child = HTMLDivElement()

    parent.append("Before", child)

    assert list(elements) == [child]
    assert len(nodes) == 2
    assert nodes[1] is child

    child.remove()

    assert list(elements) == []
    assert len(nodes) == 1

    replacement = HTMLDivElement()
    parent.replaceChildren("After", replacement)

    assert list(elements) == [replacement]
    assert len(nodes) == 2
    assert nodes[1] is replacement


def test_compact_html_nodes_materialize_dom_views_only_when_observed():
    from pyjs.web import _dom_storage

    parent = HTMLDivElement()
    child = HTMLDivElement()
    parent.setAttribute("role", "status")
    parent.append("Before", child)

    parts = _dom_storage._get_parts(parent)
    assert parts == [1, ' role="status"', "Before", child]
    assert vars(parent) == {}
    assert vars(child) == {}
    assert parent.childElementCount == 1
    assert child.parentNode is parent
    assert child.parentElement is parent
    assert "parentNode" not in vars(child)
    assert "parentElement" not in vars(child)

    attribute = parent.attributes.getNamedItem("role")
    text = parent.childNodes[0]

    assert isinstance(attribute, Attr)
    assert attribute.ownerElement is parent
    assert parts[1] == ' role="status"'
    assert isinstance(text, Text)
    assert text.data == "Before"
    assert text.parentNode is parent
    assert parts[2] is text

    attribute.value = "alert"
    parent.setAttribute("role", "note")
    assert parent.attributes.getNamedItem("role") is attribute
    assert attribute.value == "note"
    parent.removeAttribute("role")
    assert attribute.ownerElement is None


def test_compact_views_follow_attribute_boundary_changes():
    from pyjs.web import _dom_storage

    element = HTMLDivElement()
    nodes = element.childNodes
    attributes = element.attributes
    element.append("Before")

    element.setAttribute("role", "status")

    assert _dom_storage._get_parts(element)[:2] == [1, ' role="status"']
    assert nodes[0].data == "Before"
    assert attributes.getNamedItem("role").value == "status"

    element.removeAttribute("role")

    assert nodes[0].data == "Before"
    assert len(attributes) == 0


def test_compact_tag_preserves_attribute_callback_order():
    class ObservedElement(HTMLElement):
        tagName = nodeName = "OBSERVED-ELEMENT"
        observedAttributes = ["state"]

        def __init__(self):
            self.changes = []

        def attributeChangedCallback(self, name, old_value, new_value):
            self.changes.append(
                (name, old_value, new_value, len(self.childNodes))
            )

    element = ObservedElement()
    tag(element, "before", {"state": "ready", "title": "Status"}, "after")

    assert element.changes == [("state", None, "ready", 1)]
    assert element.getAttribute("title") == "Status"
    assert [node.data for node in element.childNodes] == ["before", "after"]


def test_tag_uses_application_element_builder_overrides():
    class ApplicationElement(HTMLElement):
        tagName = nodeName = "APPLICATION-ELEMENT"

        def __init__(self):
            self.builder_calls = []

        def append(self, *nodes):
            self.builder_calls.append(("append", nodes))
            super().append(*nodes)

        def setAttribute(self, name, value):
            self.builder_calls.append(("attribute", name, value))
            super().setAttribute(name, value)

    child = HTMLDivElement()
    element = ApplicationElement()
    tag(element, "before", {"state": "ready"}, child)

    assert element.builder_calls == [
        ("append", ("before",)),
        ("attribute", "state", "ready"),
        ("append", (child,)),
    ]


def test_tailwind_attribute_dictionaries_remain_independent():
    first = tw("grid gap-2")
    first["id"] = "first"

    assert tw("grid gap-2") == {"class": "grid gap-2"}


def test_class_and_dataset_views_reflect_live_attributes():
    element = HTMLDivElement()
    classes = element.classList
    dataset = element.dataset

    element.className = "panel"
    classes.add("active")
    assert element.getAttribute("class") == "panel active"

    element.setAttribute("class", "external")
    assert classes.contains("external")
    assert not classes.contains("panel")

    dataset["userId"] = "42"
    assert element.getAttribute("data-user-id") == "42"

    element.setAttribute("data-release-channel", "stable")
    assert dataset["releaseChannel"] == "stable"
    assert list(dataset) == ["userId", "releaseChannel"]
    assert list(dataset.items()) == [
        ("userId", "42"),
        ("releaseChannel", "stable"),
    ]
    assert vars(element) == {}
    assert dict(dataset.map.items()) == {
        "userId": "42",
        "releaseChannel": "stable",
    }

    del dataset["userId"]
    assert element.getAttribute("data-user-id") is None


def test_intersection_observer_bindings_are_available_from_webidl():
    observer = IntersectionObserver(lambda entries, owner: None)
    options = IntersectionObserverInit(rootMargin="200px 0px", threshold=[0, 1])
    entry = IntersectionObserverEntry

    assert observer.root is None
    assert options.rootMargin == "200px 0px"
    assert options.threshold == [0, 1]
    assert entry.__name__ == "IntersectionObserverEntry"


class JSONFixture(JSONObject):
    name: str
    values: list[int]


def test_json_uses_python_json_for_cpython_fallbacks():
    parsed: JSONFixture = JSON.parse('{"name":"PyJS","values":[1,2]}')
    assert parsed == {
        "name": "PyJS",
        "values": [1, 2],
    }
    assert JSON.stringify(JSONFixture(name="PyJS", values=[1, 2])) == (
        '{"name":"PyJS","values":[1,2]}'
    )


def test_math_random_uses_python_random_for_cpython_fallbacks():
    assert 0 <= Math.random() < 1


def test_encode_uri_component_matches_javascript_safe_characters():
    assert encodeURIComponent("build 7/ready?yes!") == (
        "build%207%2Fready%3Fyes!"
    )


def test_date_now_uses_epoch_milliseconds_for_cpython_fallback():
    before = time.time_ns() // 1_000_000
    current = Date.now()
    after = time.time_ns() // 1_000_000

    assert before <= current <= after


def test_date_construction_and_accessors_have_cpython_fallbacks():
    epoch = Date(0)
    current = Date()
    release = Date("2026-08-30T00:00:00")
    utc_release = Date("2026-08-30T00:00:00Z")

    assert epoch.toISOString() == "1970-01-01T00:00:00.000Z"
    assert 0 <= current.getMonth() <= 11
    assert 1 <= current.getDate() <= 31
    assert current.getFullYear() >= 2026
    assert release.getMonth() == 7
    assert release.getDate() == 30
    assert release.getFullYear() == 2026
    local_release = datetime.fromisoformat(
        "2026-08-30T00:00:00+00:00"
    ).astimezone()
    assert release.getHours() == 0
    assert release.getMinutes() == 0
    assert utc_release.getHours() == local_release.hour
    assert utc_release.getMinutes() == local_release.minute
    assert release.toLocaleDateString()


def test_document_create_element_works_after_direct_html_import():
    assert isinstance(document.createElement("section"), HTMLElement)
    assert document.body.style.overflow == "visible"


def test_document_create_element_ns_builds_svg_elements_for_server_rendering():
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
    line = document.createElementNS("http://www.w3.org/2000/svg", "line")
    svg.append(line)

    assert isinstance(svg, SVGSVGElement)
    assert isinstance(line, SVGLineElement)
    assert svg.namespaceURI == "http://www.w3.org/2000/svg"


def test_generated_dom_classes_preserve_inheritance_and_cpython_values():
    assert issubclass(Element, Node)
    assert issubclass(Document, Node)
    assert issubclass(DocumentFragment, Node)
    assert issubclass(CDATASection, Node)
    assert DOMRect().left == 0.0
    assert Range.START_TO_START == 0


def test_generated_mutable_dom_attributes_are_per_instance():
    first = Document()
    second = Document()

    assert first.adoptedStyleSheets is not second.adoptedStyleSheets


def test_all_node_types_materialize_inherited_state_lazily():
    nodes = [
        Node(),
        DocumentType(),
        DocumentFragment(),
        Element(),
        Document(),
        Attr(),
        Text("Hello"),
        HTMLDivElement(),
        SVGSVGElement(),
    ]

    for node in nodes:
        assert "baseURI" not in vars(node)
        assert node.baseURI == ""
        assert "baseURI" not in vars(node)

    ordinary_nodes = [nodes[index] for index in (0, 1, 2, 4, 5, 6)]
    child_lists = [node.childNodes for node in ordinary_nodes]

    for node, child_list in zip(ordinary_nodes, child_lists, strict=True):
        assert node.childNodes is child_list
        assert len(child_list) == 0
    assert len({id(child_list) for child_list in child_lists}) == len(child_lists)

    for element in (nodes[3], nodes[7], nodes[8]):
        children = element.childNodes
        assert element.childNodes is not children
        element.append("Hello")
        child = children[0]
        assert element.childNodes[0] is child

        element.setAttribute("role", "status")
        attributes = element.attributes
        assert element.attributes is not attributes
        attribute = attributes.getNamedItem("role")
        assert element.attributes.getNamedItem("role") is attribute


def test_dom_collections_are_read_only_python_sequences():
    parent = Element()
    child = Element()
    child.id = "result"

    parent.append("Total: ", child)

    assert isinstance(parent.children, HTMLCollection)
    assert isinstance(parent.childNodes, NodeList)
    assert len(parent.children) == 1
    assert parent.children[0] is child
    assert parent.children.namedItem("result") is child
    assert len(parent.childNodes) == 2
    assert isinstance(parent.childNodes[0], Text)
    assert parent.childNodes[0].data == "Total: "
    assert parent.childNodes[0].parentNode is parent
    assert child.parentNode is parent
    assert child.parentElement is parent

    child.remove()

    assert len(parent.children) == 0
    assert len(parent.childNodes) == 1
    assert child.parentNode is None
    assert child.parentElement is None


def test_named_node_map_exposes_attribute_nodes():
    element = Element()

    element.setAttribute("role", "status")

    assert isinstance(element.attributes, NamedNodeMap)
    assert len(element.attributes) == 1
    assert element.attributes[0].name == "role"
    assert element.attributes["role"].value == "status"
    assert element.getAttribute("role") == "status"

    element.removeAttribute("role")

    assert len(element.attributes) == 0
    assert element.getAttribute("role") is None


def test_network_classes_are_available_from_focused_module():
    assert isinstance(WebSocket("ws://localhost"), WebSocket)
    assert isinstance(Response(), Response)


def test_application_web_api_classes_are_available_from_focused_modules():
    assert isinstance(Blob(["note"], type="text/plain"), Blob)
    assert issubclass(File, Blob)
    assert FileList().length == 0
    assert isinstance(URL("https://pyjs.org/docs"), URL)
    assert URLSearchParams("view=notes").size == 0
    assert isinstance(indexedDB, object)
    assert issubclass(IDBDatabase, EventTarget)
    assert issubclass(IDBRequest, EventTarget)
    assert issubclass(SVGSVGElement, SVGElement)
    assert issubclass(SVGLineElement, SVGElement)


def test_typed_indexeddb_request_optionally_validates_cpython_results():
    request = IDBRequest[str]()
    request.result = "stored"

    def require_text(value):
        if not isinstance(value, str):
            raise ValueError("expected stored text")
        return value

    assert asyncio.run(request.value(require_text)) == "stored"

    request.result = 42
    with pytest.raises(ValueError, match="expected stored text"):
        asyncio.run(request.value(require_text))


def test_encoding_crypto_and_lifecycle_apis_are_available():
    assert isinstance(TextEncoder(), TextEncoder)
    assert TextDecoder(fatal=True).fatal
    assert SharedArrayBuffer(8).byteLength == 8
    assert isinstance(crypto, Crypto)
    assert issubclass(SubtleCrypto, object)
    assert issubclass(CryptoKey, object)
    assert document.hidden is False
    assert document.visibilityState == ""
    assert callable(window.confirm)


def test_service_worker_apis_are_available_from_the_focused_module():
    assert isinstance(caches, CacheStorage)
    assert navigator.serviceWorker is None
    assert issubclass(ServiceWorker, EventTarget)
    assert issubclass(ServiceWorkerRegistration, EventTarget)
    assert issubclass(FetchEvent, Event)
    assert issubclass(ServiceWorkerGlobalScope, EventTarget)
    assert issubclass(Clients, object)
    assert issubclass(Cache, object)
    assert callable(service_worker_scope)


def test_broader_generated_api_families_are_available_from_focused_modules():
    assert issubclass(Headers, object)
    assert issubclass(FormData, object)
    assert issubclass(XMLHttpRequest, EventTarget)
    assert issubclass(Notification, EventTarget)
    assert issubclass(PushManager, object)
    assert issubclass(Clipboard, EventTarget)
    assert issubclass(ClipboardEvent, Event)
    assert issubclass(ClipboardItem, object)
    assert clipboard_navigator.clipboard is None
    assert issubclass(StorageManager, object)
    assert isinstance(StorageEstimate(), StorageEstimate)
    assert storage_navigator.storage is None
