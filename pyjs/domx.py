import re

from pyjs.dom import *
from pyjs import js, nojs, js_str


@js
def tw(classes: str) -> dict[str,str]:
    return {"class": classes}


@js
def tag(name_or_element: str|HTMLElement, *args: str|dict[str,str]|HTMLElement) -> HTMLElement:
    if isinstance(name_or_element, str):
        e = document.createElement(name_or_element)
    else:
        e = name_or_element
    assert isinstance(e, HTMLElement)
    for arg in args:
        if isinstance(arg, str):
            e.append(arg)
        elif isinstance(arg, HTMLElement):
            e.append(arg)
        elif isinstance(arg, ProxyElement):
            e.append(arg.element)
        elif isinstance(arg, dict):
            attrs: dict[str,str] = arg
            for attr, value in attrs.items():
                e.setAttribute(attr, value)
        else:
            raise TypeError
    return e


class CustomElementMetaclass(type):
    def __new__(mcls, name, bases, namespace, /, **kwargs):
        if name not in ("CustomElement", "Widget"):
            tag = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', name)
            tag = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1-\2', tag)
            namespace = {
                "nodeName": js_str(tag.upper()),
                "tagName": js_str(tag.lower()),
                "__js_append__": lambda *args: f"customElements.define({repr(tag.lower())}, {name})",
                **namespace
            }
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        return cls


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
        if isinstance(value, (HTMLElement, ProxyElement)):
            if value.getAttribute("id") is not None:
                raise ValueError("element ids are used for hydration and should not be set")
            value.setAttribute("id", f"{self.get_data("self-id")}-{name}")
        super().__setattr__(name, value)

    def set_data(self, name: str, value: str):
        self.setAttribute(f"data-{name}", value)

    @js(include=True)
    def get_data(self, name:str) -> str:
        return self.getAttribute(f"data-{name}")

    @js(include=True)
    def connectedCallback(self):
        if self._initialized: return
        if self.get_data("self-id"):
            self._hydrate()
        self.initialize()
        self._initialized = True

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
    def _hydrate(self, e: HTMLElement):
        self.element = e
        return self

    def setAttribute(self, name: str, value: str):
        self.element.setAttribute(name, value)

    def getAttribute(self, name: str):
        return self.element.getAttribute(name)


@js
def div(*args) -> HTMLDivElement:
    return tag("div", *args)


@js
def span(*args) -> HTMLSpanElement:
    return tag("span", *args)


@js
def input(*args) -> HTMLInputElement:
    return tag("input", *args)


@js
def button(*args) -> HTMLButtonElement:
    return tag("button", *args)


@js
def h1(*args):
    return tag("h1", *args)
