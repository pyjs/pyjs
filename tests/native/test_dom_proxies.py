import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_existing_tag_retains_prior_children_when_a_proxy_read_fails(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ProxyElement, div, tag
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self, text: str):
        self.element = div(text)
class Panel(CustomElement):
    pass
def fail() -> str:
    raise ValueError("argument")
def check(root: Element) -> str:
    empty = ProxyElement()
    good = Box("good")
    result = ""
    try:
        tag(root, {"phase": "one"}, "kept", good, {"phase": "two"}, empty, "lost")
    except AttributeError:
        result += render_html(root)
    children: list[ProxyElement] = [good, empty, Box("lost")]
    try:
        tag(root, "star", *children)
    except AttributeError:
        result += render_html(root)
    mixed: list[str | ProxyElement] = ["union", good, empty, "lost"]
    try:
        tag(root, *mixed)
    except AttributeError:
        result += render_html(root)
    try:
        tag(root, "never", empty, fail())
    except ValueError:
        result += "argument-first" + render_html(root)
    empty._hydrate(div("ready"))
    gc_collect()
    tag(root, empty, "retry")
    return result + render_html(root)
def main() -> str:
    return check(div("root")) + check(Panel())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_proxy_forwarding_uses_real_python_methods_and_wrapper_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ProxyElement, div, span
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self, text: str):
        self.element = div(text)
        self.calls = 0
    def setAttribute(self, name: str, value: str) -> None:
        self.calls += 1
        super().setAttribute(name, value + "!")
class Child(Box):
    pass
class Panel(CustomElement):
    pass
class GenericBox[T](ProxyElement):
    def __init__(self, payload: T):
        self.payload = payload
        self.element = div(str(payload))
def set_value(box: ProxyElement) -> None:
    options = {"name": "data-x", "value": "<&"}
    box.setAttribute(**options)
def main() -> str:
    gc_set_threshold(1)
    box = Child("child")
    alias = box
    set_value(box)
    assert box.calls == 1
    assert alias is box
    assert not isinstance(box, Element)
    proxy_checks = [isinstance(box, ProxyElement), isinstance(box.element, ProxyElement)]
    assert proxy_checks == [True, False]
    assert box is not box.element
    assert box.getAttribute("data-x") == "<&!"
    before = div(box, box.element)
    saved = box.element
    box.element = span("replacement")
    box.removeAttribute("missing")
    box.setAttribute("new", "value")
    gc_collect()
    assert saved is not box.element
    assert box._hydrate(saved) is box
    gc_collect()
    result = render_html(before) + render_html(div(box)) + str(box.calls)
    box.element = Panel()
    box.setAttribute("panel", "yes")
    gc_collect()
    generic = GenericBox(42)
    assert generic.payload == 42
    gc_collect()
    return result + render_html(div(box, generic))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_proxy_builders_read_fields_after_argument_evaluation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, div, span
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self, text: str):
        self.element = div(text)
class Other(ProxyElement):
    def __init__(self):
        self.element = span("other")
def later(box: Box, children: list[Box | Other]) -> str:
    box.element = span("changed")
    children.clear()
    gc_collect()
    return "tail"
def stream(children: list[Box | Other]) -> Iterator[Box | Other]:
    for child in children:
        gc_collect()
        yield child
def main() -> str:
    gc_set_threshold(1)
    box = Box("old")
    children: list[Box | Other] = [box, Other()]
    first = div(box, later(box, children))
    box.element = div("old-again")
    children.extend([box, Other()])
    second = div(*stream(children), later(box, children))
    mixed: list[Element | Box] = [span("plain"), box]
    third = div(*mixed)
    mixed.clear()
    gc_collect()
    return render_html(first) + render_html(second) + render_html(third)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_absent_proxy_element_raises_and_can_be_initialized_later(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import ProxyElement, div
from pyjs.web.ssr import render_html
class Empty(ProxyElement):
    pass
class Other(ProxyElement):
    pass
def check(box: ProxyElement) -> str:
    result = ""
    try:
        box.getAttribute("missing")
    except AttributeError:
        result += "missing"
    try:
        div(box)
    except AttributeError:
        result += "child"
    box._hydrate(div("ready"))
    gc_collect()
    return result + render_html(div(box))
def main() -> str:
    gc_set_threshold(1)
    result = check(ProxyElement()) + check(Empty())
    values: list[Empty | Other] = [Empty(), Other()]
    for box in values:
        try:
            render_html(box.element)
        except AttributeError:
            result += "union"
        box.element = div("union-ready")
    gc_collect()
    return result + render_html(div(*values))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_proxy_does_not_gain_element_only_methods():
    with pytest.raises(CompilationError, match="querySelector"):
        transpile_llvm('''
from pyjs.web.domx import ProxyElement, div
class Box(ProxyElement):
    def __init__(self):
        self.element = div()
def main() -> int:
    return int(Box().querySelector("x") is None)
''')


@pytest.mark.parametrize("annotation", ["", "    element: HTMLInputElement\n"])
def test_proxy_backing_field_does_not_gain_concrete_html_properties(annotation):
    with pytest.raises(CompilationError, match="value.*not defined.*WebElement"):
        transpile_llvm('''
from pyjs.web.domx import ProxyElement, input
from pyjs.web.html import HTMLInputElement
class Box(ProxyElement):
''' + annotation + '''    def __init__(self):
        self.element = input()
def main() -> str:
    return Box().element.value
''')


def test_concrete_proxy_cannot_be_cast_to_a_dom_pointer():
    with pytest.raises(LLVMUnsupported):
        transpile_llvm('''
from typing import cast
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, div
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self):
        self.element = div()
def main() -> str:
    box = Box()
    return render_html(cast(Element, box))
''')


@pytest.mark.parametrize("operation,error,diagnostic", [
    ("render_html(box)", CompilationError, "expects WebElement, got Box"),
    ("render_html(tag(box, 'child'))", LLVMUnsupported, "tag requires a string or element"),
])
def test_proxy_is_not_a_rendering_or_population_root(operation, error, diagnostic):
    with pytest.raises(error, match=diagnostic):
        transpile_llvm('''
from pyjs.web.domx import ProxyElement, div, tag
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self):
        self.element = div()
def main() -> str:
    box = Box()
    return ''' + operation + '\n')


@pytest.mark.parametrize("body", [
    'element = None',
    '@property\n    def element(self) -> Element:\n        return div("property")',
    'def __getattribute__(self, name: str) -> object:\n        return object.__getattribute__(self, name)',
    'def __setattr__(self, name: str, value: object) -> None:\n        object.__setattr__(self, name, value)',
])
def test_proxy_custom_storage_requires_explicit_support(body):
    with pytest.raises(LLVMUnsupported, match="ordinary instance field"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, div
class Box(ProxyElement):
    ''' + body + '''
def main() -> int:
    box = Box()
    return int(box is not None)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_proxy_receiver_is_rooted_across_collecting_argument_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, div
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self, text: str):
        self.element = div(text)
class Holder:
    def __init__(self):
        self.value = Box("old")
def replace(holder: Holder) -> str:
    holder.value = Box("new")
    gc_collect()
    return "data-x"
def main() -> str:
    gc_set_threshold(1)
    holder = Holder()
    old_node = holder.value.element
    holder.value.setAttribute(replace(holder), "kept")
    erased: object = holder.value
    holder.value = Box("latest")
    gc_collect()
    assert isinstance(erased, Box)
    assert not isinstance(erased, Element)
    if isinstance(erased, Box):
        return render_html(old_node) + render_html(div(erased))
    return "missing"
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
