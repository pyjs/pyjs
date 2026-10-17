"""Inherited DOM defaults select subclass methods without losing wrappers."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_attribute_methods_keep_gc_roots_order_and_recovery(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html

class Base(CustomElement):
    pass
class Child(Base):
    def setAttribute(self, name: str, value: str) -> None:
        gc_collect()
        if value == "reject":
            raise ValueError("rejected")
        super().setAttribute(name, "child:" + value)
    def getAttribute(self, name: str) -> str | None:
        gc_collect()
        value = super().getAttribute(name)
        return None if value is None else "read:" + value
    def hasAttribute(self, name: str) -> bool:
        gc_collect()
        return name == "virtual" or super().hasAttribute(name)
    def removeAttribute(self, name: str) -> None:
        gc_collect()
        super().removeAttribute("x" if name == "alias" else name)
class Grandchild(Child):
    pass

def argument(owner: list[Base], events: list[str], value: str, fail: bool = False) -> str:
    events.append(value)
    owner.clear()
    gc_collect()
    if fail:
        raise ValueError("argument")
    return value

def change(value: Base, events: list[str]) -> str:
    result = ""
    for text in ["initial", "reject", "retry"]:
        try:
            value.setAttribute(value=argument([], events, text), name=argument([], events, "x"))
        except ValueError as error:
            result += str(error)
        result += str(value.getAttribute("x")) + str(value.hasAttribute("virtual"))
    value.removeAttribute("alias")
    result += str(value.getAttribute("x"))
    return result + render_html(value)

def captured(owner: list[Base], events: list[str], fail: bool) -> str:
    try:
        return str(owner[0].getAttribute(argument(owner, events, "x", fail)))
    except ValueError as error:
        return str(error)

def main() -> str:
    gc_set_threshold(1)
    values: list[Base] = [Base(), Child(), Grandchild()]
    events: list[str] = []
    result = ""
    for value in values:
        result += change(value, events)
    for fail in [False, True]:
        owner: list[Base] = [Grandchild()]
        owner[0].setAttribute("x", "saved")
        result += captured(owner, events, fail)
    return result + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
def test_inherited_children_method_keeps_expansion_and_override(tmp_path, optimize, method):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, span
from pyjs.web.ssr import render_html

class Base(CustomElement):
    pass
class Child(Base):
    def METHOD(self, *children: Element | str) -> None:
        gc_collect()
        super().METHOD("prefix:", *children)
class Grandchild(Child):
    pass

def children(fail: bool) -> Iterator[Element | str]:
    yield span("one<&")
    gc_collect()
    if fail:
        raise ValueError("children")
    yield "two"

def change(value: Base, fail: bool) -> str:
    try:
        value.METHOD(*children(fail))
    except ValueError as error:
        return str(error) + render_html(value)
    return render_html(value)

def main() -> str:
    gc_set_threshold(1)
    values: list[Base] = [Base(), Child(), Grandchild()]
    result = ""
    for value in values:
        for fail in [True, False, False]:
            result += change(value, fail)
    return result
'''.replace("METHOD", method), directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_query_and_data_helpers_keep_selected_methods(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

class Base(CustomElement):
    pass
class Child(Base):
    def set_data(self, name: str, value: str) -> None:
        gc_collect()
        super().set_data(name, "stored:" + value)
    def get_data(self, name: str) -> str | None:
        gc_collect()
        value = super().get_data(name)
        return None if value is None else "read:" + value
    def querySelector(self, selector: str) -> Element | None:
        gc_collect()
        return None if selector == "missing" else super().querySelector(selector)
class Grandchild(Child):
    pass

def read(value: Base) -> str:
    value.set_data(value="ok", name="item")
    return str(value.get_data("item")) + str(value.querySelector("missing") is None) + str(value.querySelector("self") is value)

def main() -> str:
    gc_set_threshold(1)
    values: list[Base] = [Base(), Child(), Grandchild()]
    return "|".join(read(value) for value in values)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_selected_dom_override_binds_its_own_names_and_defaults(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement
from pyjs.native import gc_collect, gc_set_threshold

class Base(CustomElement):
    pass
class Child(Base):
    def setAttribute(self, key: str, value: str = "default") -> None:
        gc_collect()
        super().setAttribute(key, value)

def arguments(events: list[str], values: dict[str, str]) -> dict[str, str]:
    events.append("arguments")
    gc_collect()
    return values

def change(value: Base, events: list[str], values: dict[str, str]) -> str:
    try:
        value.setAttribute(**arguments(events, values))
    except TypeError:
        return "binding:" + str(value.getAttribute("x"))
    return str(value.getAttribute("x"))

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    values: list[Base] = [Base(), Child()]
    result = ""
    for value in values:
        result += change(value, events, {"name": "x", "value": "named"})
        result += change(value, events, {"key": "x"})
        result += change(value, events, {"key": "x", "value": "retry"})
    return result + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_inherited_dom_method_does_not_call_a_property_as_an_instance_method():
    with pytest.raises(LLVMUnsupported, match="override requires a reached instance method"):
        transpile_llvm('''
from pyjs.web.domx import CustomElement
class Base(CustomElement):
    pass
class Child(Base):
    @property
    def getAttribute(self) -> str:
        return "not callable"
def read(value: Base) -> str | None:
    return value.getAttribute("x")
def main() -> str:
    return str(read(Child()))
''')
