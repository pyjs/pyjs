"""Custom elements, hydration references, DOM builders, and Tailwind markers."""

import re
import weakref
from typing import cast

from pyjs import js, nojs
from pyjs.decorators import ParameterLifetime, configure_js, native_operation
from pyjs.state import StateField
from pyjs.web._dom_storage import _parts, _serialize_attribute, _set_serialized_attribute
from pyjs.web.dom import Element, document
from pyjs.web.html import (
    HTMLAnchorElement,
    HTMLButtonElement,
    HTMLCanvasElement,
    HTMLDialogElement,
    HTMLDivElement,
    HTMLElement,
    HTMLElementMetaclass,
    HTMLFormElement,
    HTMLHeadingElement,
    HTMLIFrameElement,
    HTMLImageElement,
    HTMLInputElement,
    HTMLParagraphElement,
    HTMLSpanElement,
    HTMLTextAreaElement,
    _create_html_element,
    _new_html_element,
)
from pyjs.web.timers import queueMicrotask

__all__ = [
    "CustomElement",
    "ProxyElement",
    "a",
    "button",
    "canvas",
    "dialog",
    "div",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "iframe",
    "img",
    "input",
    "p",
    "ref",
    "require_closest",
    "require_element",
    "span",
    "svg_tag",
    "tag",
    "textarea",
    "tw",
]


def custom_element_javascript(
    class_name: str,
    tag_name: str,
    state_fields: dict[str, StateField],
    effects: dict[str, tuple[str, ...]],
) -> str:
    if not state_fields:
        return f"customElements.define({tag_name!r}, {class_name})"
    lines = [field.javascript(class_name) for field in state_fields.values()]
    attributes = [field.attribute_name for field in state_fields.values()]
    lines.append(f"{class_name}.observedAttributes = {attributes!r};")
    lines.append(f"{class_name}.prototype._initialize_state = function() {{")
    lines.extend(field.javascript_default() for field in state_fields.values())
    lines.append("};")
    lines.append(f"{class_name}.prototype._run_state_effects = function(name) {{")
    for field_name, method_names in effects.items():
        calls = " ".join(f"this.{method_name}();" for method_name in method_names)
        attribute_name = state_fields[field_name].attribute_name
        lines.append(f"if (name === {attribute_name!r}) {{ {calls} }}")
    lines.append("};")
    initial_methods = list(
        dict.fromkeys(
            method_name
            for method_names in effects.values()
            for method_name in method_names
        )
    )
    lines.append(f"{class_name}.prototype._run_initial_state_effects = function() {{")
    lines.extend(f"this.{method_name}();" for method_name in initial_methods)
    lines.append("};")
    lines.append(f"customElements.define({tag_name!r}, {class_name});")
    return "\n".join(lines)


class CustomElementMetaclass(HTMLElementMetaclass):
    def __new__(mcls, name, bases, namespace, /, **kwargs):
        post_definition = None
        state_fields = {}
        effects = {}
        for base in bases:
            state_fields.update(getattr(base, "__pyjs_state_fields__", {}))
            for field_name, method_names in getattr(
                base, "__pyjs_state_effects__", {}
            ).items():
                effects.setdefault(field_name, []).extend(method_names)
        for field_name, value in namespace.items():
            if isinstance(value, StateField):
                value.__set_name__(None, field_name)
                state_fields[field_name] = value
        for method_name, value in namespace.items():
            for state_field in getattr(value, "__pyjs_effect_fields__", ()):
                field_name = state_field.name
                if state_fields.get(field_name) is not state_field:
                    raise TypeError(
                        f"{name}.{method_name} depends on state field {field_name!r} "
                        "from another class"
                    )
                effects.setdefault(field_name, []).append(method_name)
        state_effects = {
            field_name: tuple(dict.fromkeys(method_names))
            for field_name, method_names in effects.items()
        }
        namespace["__pyjs_state_fields__"] = state_fields
        namespace["__pyjs_state_effects__"] = state_effects
        namespace["__pyjs_generated_methods__"] = tuple(
            dict.fromkeys(
                method_name
                for method_names in state_effects.values()
                for method_name in method_names
            )
        )
        namespace["observedAttributes"] = [
            field.attribute_name for field in state_fields.values()
        ]
        if name not in ("CustomElement", "Widget"):
            tag = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
            tag = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", tag)
            lower_tag = tag.lower()
            if "-" not in lower_tag:
                lower_tag = "pyjs-" + lower_tag
            upper_tag = lower_tag.upper()
            def post_definition(*args):
                return custom_element_javascript(
                    name,
                    lower_tag,
                    state_fields,
                    state_effects,
                )

            namespace = {
                "nodeName": upper_tag,
                "tagName": upper_tag,
                "localName": lower_tag,
                **namespace,
            }
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        if post_definition is not None:
            configure_js(cls, post_definition_source=post_definition)
        return cls

    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        state_fields = cls.__pyjs_state_fields__
        if state_fields:
            for field in state_fields.values():
                field.materialize(instance)
        instance._initialized = True
        if cls.__pyjs_state_effects__:
            instance._run_initial_effects()
        return instance


@js
class CustomElement(HTMLElement, metaclass=CustomElementMetaclass):
    """Native custom element with SSR, hydration, state, and lifecycle support."""
    CUSTOM_ELEMENT_COUNTER = 0
    __pyjs_constructor_method__ = "_create"
    __pyjs_external_methods__ = (
        "connectedCallback",
        "disconnectedCallback",
        "adoptedCallback",
        "attributeChangedCallback",
    )

    @js
    def __init__(self):
        self._initialized = False
        counter = CustomElement.CUSTOM_ELEMENT_COUNTER + 1
        CustomElement.CUSTOM_ELEMENT_COUNTER = counter
        object.__setattr__(
            self,
            "_pyjs_parts",
            [
                1,
                f' data-self-id="ce{counter}"',
            ],
        )

    @__init__.client
    def __init__(self):
        super().__init__()
        self._initialized = False

    @nojs
    def __setattr__(self, name: str, value: Element):
        if (
            isinstance(value, (Element, ProxyElement))
            and name not in {"parentElement", "parentNode"}
            and getattr(value, "__pyjs_ref__", False)
        ):
            if value.getAttribute("id") is not None:
                raise ValueError(
                    "element ids are used for hydration and should not be set"
                )
            value.setAttribute("id", f"{self.get_data('self-id')}-{name}")
        super().__setattr__(name, value)

    def set_data(self, name: str, value: str):
        self.setAttribute(f"data-{name}", value)

    def get_data(self, name: str) -> str | None:
        return self.getAttribute(f"data-{name}")

    def connectedCallback(self):
        if self._initialized:
            self.reconnected()
            return
        self._initialize_state()
        hydrated = self.get_data("self-id") is not None
        if hydrated:
            queueMicrotask(self._finish_hydration)
            return
        self._initialized = True
        self._run_initial_effects()
        self.initialize()

    def disconnectedCallback(self):
        if self._initialized:
            self.disconnected()

    def _finish_hydration(self):
        if self._initialized or not self.isConnected:
            return
        self._hydrate()
        self._initialized = True
        self.initialize()

    def attributeChangedCallback(
        self, name: str, old_value: str | None, new_value: str | None
    ):
        # CPython permits direct DOM writes before super().__init__ establishes
        # this flag. Treat that phase as uninitialized, just as in the browser.
        if old_value == new_value or not getattr(self, "_initialized", False):
            return
        self._notify_state_change(name)

    @js
    def _notify_state_change(self, name: str):
        for method_name in self.__pyjs_state_effects__.get(name.replace("-", "_"), ()):
            getattr(self, method_name)()

    @_notify_state_change.client
    def _notify_state_change(self, name: str):
        self._run_state_effects(name)

    @js
    def _run_initial_effects(self):
        method_names = []
        for effect_methods in self.__pyjs_state_effects__.values():
            for method_name in effect_methods:
                if method_name not in method_names:
                    method_names.append(method_name)
                    getattr(self, method_name)()

    @_run_initial_effects.client
    def _run_initial_effects(self):
        self._run_initial_state_effects()

    def _initialize_state(self):
        pass

    def _run_state_effects(self, name: str):
        pass

    def _run_initial_state_effects(self):
        pass

    def _create(self, *args):
        return tag(self, *args)

    def _hydrate(self):
        pass

    def initialize(self):
        pass

    def reconnected(self):
        pass

    def disconnected(self):
        pass


@js
class ProxyElement:
    """Python wrapper that delegates DOM operations to an owned element."""
    element: Element
    __pyjs_constructor_method__ = "_create"
    __pyjs_reference_method__ = "_hydrate"

    def _create(self, *args):
        return tag(self, *args)

    def _hydrate(self, e: Element):
        self.element = e
        return self

    def setAttribute(self, name: str, value: str):
        self.element.setAttribute(name, value)

    def getAttribute(self, name: str):
        return self.element.getAttribute(name)

    def removeAttribute(self, name: str):
        self.element.removeAttribute(name)


@native_operation("reference", value=ParameterLifetime.RETURNED)
@js.inline("{value}")
def ref[T](value: T) -> T:
    """Retain an element as an instance reference during hydration."""
    if isinstance(value, (Element, ProxyElement)):
        value.__pyjs_ref__ = True
    return value


@ref.analyze
def ref(call):
    return call.preserve_reference()


@js
def require_element(root: Element, selector: str) -> Element:
    """Return a required descendant or raise with its selector."""
    element = root.querySelector(selector)
    if element is None:
        raise ValueError("Required element not found: " + selector)
    return element


@js
def require_closest(element: Element, selector: str) -> Element:
    """Return a required matching ancestor or raise with its selector."""
    ancestor = element.closest(selector)
    if ancestor is None:
        raise ValueError("Required ancestor not found: " + selector)
    return ancestor


# @js
class ContextProxy[V]:
    def __init__(self):
        self._context: V = None

    def set(self, context: V):
        self._context = context

    def get(self) -> V:
        return self._context


# @js
class ContextProvider:
    def __init__(self):
        self.contexts: dict[type, ContextProxy[object]] = {}

    def register(self, context_type: type, context: object):
        self.contexts[context_type].set(context)
        self.contexts[context_type] = ContextProxy[object]()

    def get_proxy(self, context_type: type):
        if context_type not in self.contexts:
            self.contexts[context_type] = ContextProxy[object]()
        return self.contexts[context_type]


context = ContextProvider()
# js.native(context)


@native_operation("class_attribute", classes=ParameterLifetime.RETURNED)
@js
def tw(classes: str) -> dict[str, str]:
    """Mark Tailwind classes for extraction and return a class attribute."""
    return {"class": classes}


def _populate_compact_element(e, parts, args):
    if parts is None:
        element_type = e
        e = element_type.__new__(element_type)
        parts = [0]
        object.__setattr__(e, "_pyjs_parts", parts)
    parent_reference = None
    for arg in args:
        arg_type = type(arg)
        if arg_type is str:
            parts.append(arg)
        elif arg_type is dict:
            # Keep this direct-attribute block in sync with the matching block
            # in tag(). The latter still needs it when setAttribute is direct
            # but append is overridden. Both remain inline to preserve the
            # benchmarked compact-construction shape.
            attrs: dict[str, str] = arg
            if len(attrs) == 1 and "class" in attrs:
                value = attrs["class"]
                if parts[0] == 0:
                    parts[0] = 1
                    fragment = _serialize_attribute("class", value)
                    if len(parts) == 1:
                        parts.append(fragment)
                    else:
                        parts.insert(1, fragment)
                else:
                    _set_serialized_attribute(parts, "class", value)
                continue
            if (
                parts[0] == 1
                and len(parts) == 2
                and parts[1].startswith(' class="')
                and "class" not in attrs
            ):
                parts[0] += len(attrs)
                parts.extend(
                    [
                        _serialize_attribute(attr, value)
                        for attr, value in attrs.items()
                    ]
                )
                continue
            if parts[0] == 0:
                if not attrs:
                    continue
                parts[0] = len(attrs)
                fragments = [
                    _serialize_attribute(attr, value)
                    for attr, value in attrs.items()
                ]
                if len(parts) == 1:
                    parts.extend(fragments)
                else:
                    parts[1:1] = fragments
                continue
            for attr, value in attrs.items():
                _set_serialized_attribute(parts, attr, value)
        elif isinstance(arg, Element):
            if parent_reference is None:
                parent_reference = weakref.ref(e)
            object.__setattr__(arg, "_pyjs_parent", parent_reference)
            parts.append(arg)
        elif isinstance(arg, ProxyElement):
            element = arg.element
            if parent_reference is None:
                parent_reference = weakref.ref(e)
            object.__setattr__(element, "_pyjs_parent", parent_reference)
            parts.append(element)
        elif isinstance(arg, str):
            parts.append(arg)
        elif isinstance(arg, dict):
            for attr, value in arg.items():
                _set_serialized_attribute(parts, attr, value)
        else:
            raise TypeError()
    return e


@native_operation(
    "tag",
    name_or_element=ParameterLifetime.BORROWED,
    args=ParameterLifetime.BORROWED,
)
@js
def tag(
    name_or_element: str | HTMLElement | ProxyElement,
    *args: str | dict[str, str] | Element | ProxyElement,
) -> HTMLElement:
    """Create or populate an HTML element from children and attributes."""
    if type(name_or_element) is str or isinstance(name_or_element, str):
        e = _create_html_element(name_or_element)
        return _populate_compact_element(e, e._pyjs_parts, args)
    e = name_or_element
    element_type = type(e)
    try:
        parts = e._pyjs_parts
    except AttributeError:
        parts = _parts(e)
    direct_attributes = element_type.__pyjs_direct_attributes__
    direct_append = element_type.__pyjs_direct_append__
    observed_attributes = element_type.__pyjs_observed_attributes__
    if (
        direct_attributes
        and direct_append
        and not observed_attributes
        and parts[0] >= 0
    ):
        return _populate_compact_element(e, parts, args)
    for arg in args:
        arg_type = type(arg)
        if arg_type is str:
            if direct_append:
                parts.append(arg)
            else:
                e.append(arg)
        elif arg_type is dict:
            attrs: dict[str, str] = arg
            if not direct_attributes:
                for attr, value in attrs.items():
                    e.setAttribute(attr, value)
                continue
            if parts[0] < 0:
                for attr, value in attrs.items():
                    e.setAttribute(attr, value)
                continue
            if observed_attributes:
                for attr, value in attrs.items():
                    if attr in observed_attributes:
                        e.setAttribute(attr, value)
                    else:
                        _set_serialized_attribute(parts, attr, value)
                continue
            # This repeats _populate_compact_element's direct-attribute block
            # for elements that retain direct attributes but need another
            # builder hook. Change both copies together and rerun the SSR
            # construction benchmark.
            if len(attrs) == 1 and "class" in attrs:
                value = attrs["class"]
                if parts[0] == 0:
                    parts[0] = 1
                    fragment = _serialize_attribute("class", value)
                    if len(parts) == 1:
                        parts.append(fragment)
                    else:
                        parts.insert(1, fragment)
                else:
                    _set_serialized_attribute(parts, "class", value)
                continue
            if (
                parts[0] == 1
                and len(parts) == 2
                and parts[1].startswith(' class="')
                and "class" not in attrs
            ):
                parts[0] += len(attrs)
                parts.extend([
                    _serialize_attribute(attr, value)
                    for attr, value in attrs.items()
                ])
                continue
            if parts[0] == 0:
                if not attrs:
                    continue
                parts[0] = len(attrs)
                fragments = [
                    _serialize_attribute(attr, value)
                    for attr, value in attrs.items()
                ]
                if len(parts) == 1:
                    parts.extend(fragments)
                else:
                    parts[1:1] = fragments
                continue
            for attr, value in attrs.items():
                _set_serialized_attribute(parts, attr, value)
        elif isinstance(arg, Element):
            element = arg
            if direct_append:
                object.__setattr__(element, "_pyjs_parent", weakref.ref(e))
                parts.append(element)
            else:
                element.parentElement = e
                e.append(element)
        elif isinstance(arg, ProxyElement):
            element = arg.element
            if direct_append:
                object.__setattr__(element, "_pyjs_parent", weakref.ref(e))
                parts.append(element)
            else:
                element.parentElement = e
                e.append(element)
        elif isinstance(arg, str):
            if direct_append:
                parts.append(arg)
            else:
                e.append(arg)
        elif isinstance(arg, dict):
            for attr, value in arg.items():
                e.setAttribute(attr, value)
        else:
            raise TypeError()
    return e


@tag.client
def tag(
    name_or_element: str | HTMLElement | ProxyElement,
    *args: str | dict[str, str] | Element | ProxyElement,
) -> HTMLElement:
    if isinstance(name_or_element, str):
        e = cast(HTMLElement, document.createElement(name_or_element))
    else:
        # The constructor hook also passes an unhydrated ProxyElement
        # placeholder with no children. This is a static builder interface,
        # not an instanceof requirement: ref() hydrates the wrapper afterward.
        e = cast(HTMLElement, name_or_element)
    for arg in args:
        if isinstance(arg, str):
            e.append(arg)
        elif isinstance(arg, Element):
            e.append(arg)
        elif isinstance(arg, ProxyElement):
            e.append(arg.element)
        elif isinstance(arg, dict):
            attrs: dict[str, str] = arg
            for attr, value in attrs.items():
                e.setAttribute(attr, value)
        else:
            raise TypeError()
    return e


@native_operation(
    "tag",
    name=ParameterLifetime.BORROWED,
    args=ParameterLifetime.BORROWED,
)
@js
def svg_tag(
    name: str,
    *args: str | dict[str, str] | Element | ProxyElement,
) -> Element:
    """Create an SVG namespace element from children and attributes."""
    e = document.createElementNS("http://www.w3.org/2000/svg", name)
    for arg in args:
        if isinstance(arg, str):
            e.append(arg)
        elif isinstance(arg, Element):
            arg.parentElement = e
            e.append(arg)
        elif isinstance(arg, ProxyElement):
            arg.element.parentElement = e
            e.append(arg.element)
        elif isinstance(arg, dict):
            attrs: dict[str, str] = arg
            for attr, value in attrs.items():
                e.setAttribute(attr, value)
        else:
            raise TypeError()
    return e


@svg_tag.client
def svg_tag(
    name: str,
    *args: str | dict[str, str] | Element | ProxyElement,
) -> Element:
    e = document.createElementNS("http://www.w3.org/2000/svg", name)
    for arg in args:
        if isinstance(arg, str):
            e.append(arg)
        elif isinstance(arg, Element):
            e.append(arg)
        elif isinstance(arg, ProxyElement):
            e.append(arg.element)
        elif isinstance(arg, dict):
            attrs: dict[str, str] = arg
            for attr, value in attrs.items():
                e.setAttribute(attr, value)
        else:
            raise TypeError()
    return e


def html_tag(name: str):
    def decorate(builder):
        builder = js.inline(
            f"{{tag}}({name!r}{{*args}})",
            tag=tag,
        )(builder)
        return native_operation(
            "element",
            name,
            args=ParameterLifetime.BORROWED,
        )(builder)

    return decorate


@html_tag("div")
def div(*args) -> HTMLDivElement:
    return _populate_compact_element(HTMLDivElement, None, args)


@html_tag("span")
def span(*args) -> HTMLSpanElement:
    return _populate_compact_element(HTMLSpanElement, None, args)


@html_tag("form")
def form(*args) -> HTMLFormElement:
    return _populate_compact_element(HTMLFormElement, None, args)


@html_tag("dialog")
def dialog(*args) -> HTMLDialogElement:
    return _populate_compact_element(HTMLDialogElement, None, args)


@html_tag("input")
def input(*args) -> HTMLInputElement:
    return _populate_compact_element(HTMLInputElement, None, args)


@html_tag("textarea")
def textarea(*args) -> HTMLTextAreaElement:
    return _populate_compact_element(HTMLTextAreaElement, None, args)


@html_tag("img")
def img(*args) -> HTMLImageElement:
    return _populate_compact_element(HTMLImageElement, None, args)


@html_tag("canvas")
def canvas(*args) -> HTMLCanvasElement:
    return _populate_compact_element(HTMLCanvasElement, None, args)


@html_tag("iframe")
def iframe(*args) -> HTMLIFrameElement:
    return _populate_compact_element(HTMLIFrameElement, None, args)


@html_tag("button")
def button(*args) -> HTMLButtonElement:
    return _populate_compact_element(HTMLButtonElement, None, args)


@html_tag("a")
def a(*args) -> HTMLAnchorElement:
    return _populate_compact_element(HTMLAnchorElement, None, args)


@html_tag("p")
def p(*args) -> HTMLParagraphElement:
    return _populate_compact_element(HTMLParagraphElement, None, args)


@html_tag("h1")
def h1(*args) -> HTMLHeadingElement:
    h = _new_html_element(HTMLHeadingElement)
    h.tagName = "H1"
    h.nodeName = "H1"
    _populate_compact_element(h, h._pyjs_parts, args)
    return h


@html_tag("h2")
def h2(*args) -> HTMLHeadingElement:
    h = _new_html_element(HTMLHeadingElement)
    h.tagName = "H2"
    h.nodeName = "H2"
    _populate_compact_element(h, h._pyjs_parts, args)
    return h


@html_tag("h3")
def h3(*args) -> HTMLHeadingElement:
    h = _new_html_element(HTMLHeadingElement)
    h.tagName = "H3"
    h.nodeName = "H3"
    _populate_compact_element(h, h._pyjs_parts, args)
    return h


@html_tag("h4")
def h4(*args) -> HTMLHeadingElement:
    h = _new_html_element(HTMLHeadingElement)
    h.tagName = "H4"
    h.nodeName = "H4"
    _populate_compact_element(h, h._pyjs_parts, args)
    return h


@html_tag("h5")
def h5(*args) -> HTMLHeadingElement:
    h = _new_html_element(HTMLHeadingElement)
    h.tagName = "H5"
    h.nodeName = "H5"
    _populate_compact_element(h, h._pyjs_parts, args)
    return h


@html_tag("h6")
def h6(*args) -> HTMLHeadingElement:
    h = _new_html_element(HTMLHeadingElement)
    h.tagName = "H6"
    h.nodeName = "H6"
    _populate_compact_element(h, h._pyjs_parts, args)
    return h
