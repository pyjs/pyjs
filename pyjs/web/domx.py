import re
from functools import partial

from pyjs import js, nojs
from pyjs.state import StateField
from pyjs.web.dom import Element, document
from pyjs.web.html import (
    HTMLAnchorElement,
    HTMLButtonElement,
    HTMLCanvasElement,
    HTMLDialogElement,
    HTMLDivElement,
    HTMLElement,
    HTMLFormElement,
    HTMLHeadingElement,
    HTMLIFrameElement,
    HTMLImageElement,
    HTMLInputElement,
    HTMLParagraphElement,
    HTMLSpanElement,
    HTMLTextAreaElement,
)


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


class CustomElementMetaclass(type):
    def __new__(mcls, name, bases, namespace, /, **kwargs):
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
            namespace = {
                "nodeName": upper_tag,
                "tagName": upper_tag,
                "localName": lower_tag,
                "__js_append__": lambda *args: custom_element_javascript(
                    name, lower_tag, state_fields, state_effects
                ),
                **namespace,
            }
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        return cls

    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        for field in cls.__pyjs_state_fields__.values():
            field.materialize(instance)
        instance._initialized = True
        instance._run_initial_effects()
        return instance


@js
class CustomElement(HTMLElement, metaclass=CustomElementMetaclass):
    CUSTOM_ELEMENT_COUNTER = 0

    @js
    def __init__(self):
        super().__init__()
        self._initialized = False
        CustomElement.CUSTOM_ELEMENT_COUNTER += 1
        self.set_data("self-id", f"ce{CustomElement.CUSTOM_ELEMENT_COUNTER}")

    @__init__.client
    def __init__(self):
        super().__init__()
        self._initialized = False

    @nojs
    def __setattr__(self, name: str, value: HTMLElement):
        if (
            isinstance(value, (HTMLElement, ProxyElement))
            and name != "parentElement"
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

    @js(include=True)
    def get_data(self, name: str) -> str | None:
        return self.getAttribute(f"data-{name}")

    @js(include=True)
    def connectedCallback(self):
        if self._initialized:
            return
        self._initialize_state()
        hydrated = self.get_data("self-id") is not None
        if hydrated:
            self._hydrate()
        self._initialized = True
        if not hydrated:
            self._run_initial_effects()
        self.initialize()

    @js(include=True)
    def attributeChangedCallback(
        self, name: str, old_value: str | None, new_value: str | None
    ):
        if old_value == new_value or not self._initialized:
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

    @js(include=True)
    def _initialize_state(self):
        pass

    @js(include=True)
    def _run_state_effects(self, name: str):
        pass

    @js(include=True)
    def _run_initial_state_effects(self):
        pass

    @js(include=True)
    def _create(self, *args):
        return tag(self, *args)

    @js(include=True)
    def _hydrate(self):
        pass

    @js(include=True)
    def initialize(self):
        pass


@js
class ProxyElement:
    @js(include=True)
    def _create(self, *args):
        return tag(self, *args)

    @js(include=True)
    def _hydrate(self, e: Element):
        self.element = e
        return self

    def setAttribute(self, name: str, value: str):
        self.element.setAttribute(name, value)

    def getAttribute(self, name: str):
        return self.element.getAttribute(name)


@js(inline="{value}")
# TODO:
# def ref[T](value: T) -> T:
def ref(value: object) -> object:
    if isinstance(value, (HTMLElement, ProxyElement)):
        value.__pyjs_ref__ = True
    return value


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
# js_object(context)


@js
def tw(classes: str) -> dict[str, str]:
    return {"class": classes}


@js
def tag(
    name_or_element: str | HTMLElement,
    *args: str | dict[str, str] | HTMLElement | ProxyElement,
) -> HTMLElement:
    if isinstance(name_or_element, str):
        e = document.createElement(name_or_element)
    else:
        e = name_or_element
    assert isinstance(e, HTMLElement)
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
            raise TypeError
    return e


@tag.client
def tag(
    name_or_element: str | HTMLElement,
    *args: str | dict[str, str] | HTMLElement | ProxyElement,
) -> HTMLElement:
    if isinstance(name_or_element, str):
        e = document.createElement(name_or_element)
    else:
        e = name_or_element
    assert isinstance(e, HTMLElement)
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
            raise TypeError
    return e


@js(client=partial(tag, "div"))
def div(*args) -> HTMLDivElement:
    div_element = HTMLDivElement()
    tag(div_element, *args)
    return div_element


@js(client=partial(tag, "span"))
def span(*args) -> HTMLSpanElement:
    span_element = HTMLSpanElement()
    tag(span_element, *args)
    return span_element


@js(client=partial(tag, "form"))
def form(*args) -> HTMLFormElement:
    form_element = HTMLFormElement()
    tag(form_element, *args)
    return form_element


@js(client=partial(tag, "dialog"))
def dialog(*args) -> HTMLDialogElement:
    dialog_element = HTMLDialogElement()
    tag(dialog_element, *args)
    return dialog_element


@js(client=partial(tag, "input"))
def input(*args) -> HTMLInputElement:
    input_element = HTMLInputElement()
    tag(input_element, *args)
    return input_element


@js(client=partial(tag, "textarea"))
def textarea(*args) -> HTMLTextAreaElement:
    textarea_element = HTMLTextAreaElement()
    tag(textarea_element, *args)
    return textarea_element


@js(client=partial(tag, "img"))
def img(*args) -> HTMLImageElement:
    image_element = HTMLImageElement()
    tag(image_element, *args)
    return image_element


@js(builtin=True, inline="document.createElement('canvas')")
def canvas() -> HTMLCanvasElement:
    return HTMLCanvasElement()


@js(client=partial(tag, "iframe"))
def iframe(*args) -> HTMLIFrameElement:
    iframe_element = HTMLIFrameElement()
    tag(iframe_element, *args)
    return iframe_element


@js(client=partial(tag, "button"))
def button(*args) -> HTMLButtonElement:
    button_element = HTMLButtonElement()
    tag(button_element, *args)
    return button_element


@js(client=partial(tag, "a"))
def a(*args) -> HTMLAnchorElement:
    anchor = HTMLAnchorElement()
    tag(anchor, *args)
    return anchor


@js(client=partial(tag, "p"))
def p(*args) -> HTMLParagraphElement:
    paragraph = HTMLParagraphElement()
    tag(paragraph, *args)
    return paragraph


@js(client=partial(tag, "h1"))
def h1(*args) -> HTMLHeadingElement:
    h = HTMLHeadingElement()
    h.tagName = "H1"
    h.nodeName = "H1"
    tag(h, *args)
    return h


@js(client=partial(tag, "h2"))
def h2(*args) -> HTMLHeadingElement:
    h = HTMLHeadingElement()
    h.tagName = "H2"
    h.nodeName = "H2"
    tag(h, *args)
    return h


@js(client=partial(tag, "h3"))
def h3(*args) -> HTMLHeadingElement:
    h = HTMLHeadingElement()
    h.tagName = "H3"
    h.nodeName = "H3"
    tag(h, *args)
    return h


@js(client=partial(tag, "h4"))
def h4(*args) -> HTMLHeadingElement:
    h = HTMLHeadingElement()
    h.tagName = "H4"
    h.nodeName = "H4"
    tag(h, *args)
    return h


@js(client=partial(tag, "h5"))
def h5(*args) -> HTMLHeadingElement:
    h = HTMLHeadingElement()
    h.tagName = "H5"
    h.nodeName = "H5"
    tag(h, *args)
    return h


@js(client=partial(tag, "h6"))
def h6(*args) -> HTMLHeadingElement:
    h = HTMLHeadingElement()
    h.tagName = "H6"
    h.nodeName = "H6"
    tag(h, *args)
    return h
