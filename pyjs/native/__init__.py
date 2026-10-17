"""CPython fallbacks for DOM operations emitted by the native backend."""

import gc
from dataclasses import dataclass

from pyjs.decorators import ParameterLifetime, native_operation
from pyjs.web.domx import div as dom_div
from pyjs.web.domx import p as dom_paragraph
from pyjs.web.domx import span as dom_span
from pyjs.web.domx import tag as dom_tag
from pyjs.web.ssr import render_html, write_html_fd


def _declaration(target=None, **lifetimes: object):
    if target is None:
        return lambda target: _declaration(target, **lifetimes)
    return native_operation(f"runtime.{target.__name__}", **lifetimes)(target)


_gc_pins = {}
_gc_threshold = 4096
_gc_byte_threshold = 8_388_608


@_declaration(value=ParameterLifetime.EXTERNAL)
def gc_pin(value: object) -> None:
    """Keep a value alive across explicit native collection points."""
    _gc_pins[id(value)] = value


@_declaration(value=ParameterLifetime.BORROWED)
def gc_unpin(value: object) -> None:
    """Release one explicitly pinned value."""
    _gc_pins.pop(id(value), None)


@_declaration
def gc_collect() -> None:
    """Run the backend collector at an explicit safe point."""
    gc.collect()


@_declaration
def gc_count() -> int:
    """Return the number of explicitly pinned CPython fallback values."""
    return len(_gc_pins)


@_declaration
def gc_enable() -> None:
    """Enable automatic native collection at statement safe points."""
    gc.enable()


@_declaration
def gc_disable() -> None:
    """Disable automatic collection while retaining explicit collection."""
    gc.disable()


@_declaration
def gc_is_enabled() -> bool:
    """Return whether automatic collection is enabled."""
    return gc.isenabled()


@_declaration
def gc_set_threshold(value: int, *, byte_limit: int = 8_388_608) -> None:
    """Schedule collection when either positive allocation budget is reached.

    Native bytes include payloads and GC headers allocated since collection.
    This is a safe-point trigger, not a hard memory limit. The CPython fallback
    validates and records the budgets without changing Python's GC thresholds.
    """
    global _gc_threshold, _gc_byte_threshold
    if value < 1:
        raise ValueError("GC threshold must be positive")
    if byte_limit < 1:
        raise ValueError("GC byte threshold must be positive")
    _gc_threshold = value
    _gc_byte_threshold = byte_limit


@_declaration
@dataclass(frozen=True)
class Element:
    _value: object


@_declaration
@dataclass(frozen=True)
class Attribute:
    name: str
    value: str


def _arguments(arguments):
    values = []
    for argument in arguments:
        if isinstance(argument, Attribute):
            values.append({argument.name: argument.value})
        elif isinstance(argument, Element):
            values.append(argument._value)
        else:
            values.append(argument)
    return values


@_declaration
class Document:
    @_declaration(
        self=ParameterLifetime.BORROWED,
        name=ParameterLifetime.BORROWED,
        arguments=ParameterLifetime.BORROWED,
    )
    def element(self, name: str, *arguments: object) -> Element:
        return Element(dom_tag(name, *_arguments(arguments)))

    @_declaration(
        self=ParameterLifetime.BORROWED,
        root=ParameterLifetime.BORROWED,
    )
    def render(self, root: Element) -> str:
        return render_html(root._value)

    @_declaration(
        self=ParameterLifetime.BORROWED,
        root=ParameterLifetime.BORROWED,
        descriptor=ParameterLifetime.BORROWED,
    )
    def write(self, root: Element, descriptor: int) -> int:
        return write_html_fd(root._value, descriptor)


@_declaration(
    name=ParameterLifetime.BORROWED,
    value=ParameterLifetime.BORROWED,
)
def attr(name: str, value: str) -> Attribute:
    return Attribute(name, value)


@_declaration(value=ParameterLifetime.BORROWED)
def cls(value: str) -> Attribute:
    return Attribute("class", value)


@_declaration(
    document=ParameterLifetime.BORROWED,
    arguments=ParameterLifetime.BORROWED,
)
def div(document: Document, *arguments: object) -> Element:
    return Element(dom_div(*_arguments(arguments)))


@_declaration(
    document=ParameterLifetime.BORROWED,
    arguments=ParameterLifetime.BORROWED,
)
def paragraph(document: Document, *arguments: object) -> Element:
    return Element(dom_paragraph(*_arguments(arguments)))


@_declaration(
    document=ParameterLifetime.BORROWED,
    arguments=ParameterLifetime.BORROWED,
)
def span(document: Document, *arguments: object) -> Element:
    return Element(dom_span(*_arguments(arguments)))


@_declaration(
    document=ParameterLifetime.BORROWED,
    name=ParameterLifetime.BORROWED,
    arguments=ParameterLifetime.BORROWED,
)
def tag(
    document: Document,
    name: str,
    *arguments: object,
) -> Element:
    return Element(dom_tag(name, *_arguments(arguments)))


__all__ = [
    "Attribute",
    "Document",
    "Element",
    "attr",
    "cls",
    "div",
    "gc_collect",
    "gc_count",
    "gc_disable",
    "gc_enable",
    "gc_is_enabled",
    "gc_pin",
    "gc_set_threshold",
    "gc_unpin",
    "paragraph",
    "span",
    "tag",
]
