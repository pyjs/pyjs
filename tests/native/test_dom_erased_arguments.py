"""Object transport must keep DOM, application and collection layouts distinct."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_builder_arguments_preserve_payloads(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, span, tag, tw
from pyjs.web.ssr import render_html
class Child(CustomElement):
    def __init__(self):
        super().__init__()
        tag(self, 'custom')
def panel(*children: object) -> Element:
    gc_collect()
    return div(*children)
def main() -> str:
    gc_set_threshold(1)
    return render_html(panel(tw('group'), 'start<', span('middle'), Child(), 'end'))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_dom_identity_and_narrowing(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import cast
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html
class Child(CustomElement):
    pass
def same(left: object, right: object) -> bool:
    return left is right
def checked(value: object) -> Element:
    assert bool(value)
    assert isinstance(value, Element)
    gc_collect()
    return cast(Element, value)
def main() -> str:
    gc_set_threshold(1)
    element = div('plain')
    child = Child()
    assert same(element, element)
    assert not same(element, child)
    plain: object = element
    custom: object = child
    assert checked(plain) is element
    assert checked(custom) is child
    assert not isinstance(cast(object, 'text'), Element)
    assert not isinstance(cast(object, None), Element)
    tag(checked(plain), 'later')
    tag(checked(custom), 'custom')
    return render_html(div(element, child))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("invalid", ["None", "42", "b'bytes'", "[1, 2]"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_invalid_arguments_keep_evaluation_and_mutation_prefix(tmp_path, invalid, optimize):
    comparison = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, tag
from pyjs.web.ssr import render_html
def update(element: Element, *values: object) -> None:
    tag(element, *values)
def late(log: list[str]) -> str:
    log.append('evaluated')
    gc_collect()
    return 'unpublished'
def main() -> str:
    gc_set_threshold(1)
    log: list[str] = []
    element = div('initial')
    try:
        update(element, {{'data-prefix': 'yes'}}, 'before', {invalid}, late(log))
    except TypeError:
        log.append('caught')
    update(element, 'recovered')
    return render_html(element) + repr(log)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_attributes_are_read_after_later_arguments(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import div
from pyjs.web.ssr import render_html
def later(attributes: dict[str, str]) -> str:
    attributes['data-value'] = 'changed'
    gc_collect()
    return 'last'
def panel(attributes: object, original: dict[str, str]) -> Element:
    return div(attributes, later(original))
def main() -> str:
    attributes = {'data-value': 'initial'}
    return render_html(panel(attributes, attributes))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_proxy_expansion_snapshots_values_not_dom_fields(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, div, span, tag
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self): self.element = div('old')
def stream(values: list[object]) -> Iterator[object]:
    for value in values:
        gc_collect()
        yield value
def later(box: Box, values: list[object]) -> str:
    box.element = span('changed')
    values.clear()
    gc_collect()
    return 'tail'
def panel(box: Box, values: list[object]) -> Element:
    return div(*stream(values), later(box, values))
def update(element: Element, *values: object) -> None:
    tag(element, *values)
def main() -> str:
    gc_set_threshold(1)
    box = Box()
    values: list[object] = ['head', box]
    result = panel(box, values)
    empty = ProxyElement()
    try:
        update(result, 'kept', empty, 'lost')
    except AttributeError:
        empty._hydrate(div('ready'))
    update(result, empty)
    return render_html(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_framework_helpers_forward_erased_ui_children(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.domx import span
from pyjs.web.ui.alert import Alert, AlertTitle, AlertDescription
from pyjs.web.ui.badge import Badge
from pyjs.web.ssr import render_html
def main() -> str:
    badge = Badge('restart', variant='outline')
    gc_collect()
    return render_html(Alert(AlertTitle('Memory ', badge),
                             AlertDescription(span('safe <&>')), variant='destructive'))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("method", ["append", "setAttribute"])
def test_erased_builders_do_not_bypass_custom_mutation_methods(method):
    declaration = ("def append(self, *values: str | Element) -> None: pass" if method == "append"
                   else "def setAttribute(self, name: str, value: str) -> None: pass")
    value = "'child'" if method == "append" else "{'name': 'value'}"
    operation = "append" if method == "append" else "attribute"
    with pytest.raises(LLVMUnsupported, match=f"DOM {operation} overrides require a concrete"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
class Panel(CustomElement):
    {declaration}
def update(panel: Panel, *values: object) -> None:
    tag(panel, *values)
def main() -> int:
    update(Panel(), {value})
    return 0
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_builder_allocation_failures_can_retry(tmp_path, optimize):
    source = transpile_llvm('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, span, tag
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm, remaining
def update(target: Element, *values: object) -> None:
    tag(target, *values)
def main() -> int:
    gc_set_threshold(1)
    child = span('child')
    attributes = {'title': 'new'}
    stage = 0
    stages = 1
    while stage <= stages:
        target = div('old')
        caught = False
        arm(1000 if stage == 0 else stage)
        try:
            update(target, attributes, 'text', child)
        except MemoryError:
            caught = True
        if stage == 0:
            stages = 1000 - remaining()
        arm(0)
        assert stages > 0
        assert caught == (stage != 0)
        gc_collect()
        if caught:
            assert render_html(target) == '<div>old</div>'
            update(target, attributes, 'text', child)
        assert render_html(target) == '<div title="new">oldtext<span>child</span></div>'
        assert attributes['title'] == 'new'
        assert render_html(child) == '<span>child</span>'
        stage += 1
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dom_transport_does_not_poison_unrelated_erased_formatting(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import div
from pyjs.web.ssr import render_html
def panel(value: object) -> Element:
    return div(value)
def describe(value: object) -> str:
    return str(value)
def equal(left: object, right: object) -> bool:
    return left == right
def main() -> str:
    assert equal('text', 'text')
    return render_html(panel(div('child'))) + describe('safe')
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_dom_cast_rejects_non_nodes_at_runtime(tmp_path, optimize):
    result = LLVM().run_source('''
from typing import cast
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import ProxyElement, div
from pyjs.web.ssr import render_html
class Empty:
    pass
def checked(value: object) -> Element:
    gc_collect()
    return cast(Element, value)
def main() -> str:
    values: list[object] = [ProxyElement()._hydrate(div()), Empty(), 'text', 1, None]
    caught = 0
    for value in values:
        try:
            checked(value)
        except TypeError:
            caught += 1
    return str(caught) + render_html(checked(div('valid')))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # CPython cast() is unchecked; native projections validate before exposing
    # the DOM pointer. In particular a ProxyElement is not itself a DOM node.
    assert result.returncode == 0
    assert result.stdout == '5<div>valid</div>'
    assert result.stderr == ""


@pytest.mark.parametrize("method", ["__bool__", "__len__"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_opaque_dom_erasure_preserves_truth_dispatch(tmp_path, method, optimize):
    declaration = ("def __bool__(self) -> bool: return False" if method == "__bool__"
                   else "def __len__(self) -> int: return 0")
    comparison = LLVM().assert_matches_python(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    {declaration}
def erased(value: Element) -> object:
    return value
def main() -> int:
    return int(bool(erased(Panel())))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_dom_equality_and_formatting_keep_explicit_boundaries(tmp_path, optimize):
    result = LLVM().run_source('''
from pyjs.web.domx import div
def equal(left: object, right: object) -> bool:
    return left == right
def describe(value: object) -> str:
    return str(value)
def main() -> int:
    element = div()
    caught = 0
    try:
        equal(element, element)
    except TypeError:
        caught += 1
    try:
        describe(element)
    except TypeError:
        caught += 1
    assert equal('safe', 'safe')
    assert describe(42) == '42'
    return caught
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # Transport/is/Element projections do not add opaque rich-comparison or
    # object-repr semantics. Unsupported selected layouts fail, unrelated ones run.
    assert result.returncode == 2
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("interface", ["HTMLElement", "HTMLDivElement", "HTMLInputElement"])
def test_erased_dom_cast_does_not_invent_concrete_html_identity(interface):
    with pytest.raises(LLVMUnsupported, match="DOM narrowing supports Element, not concrete DOM interfaces"):
        transpile_llvm(f'''
from typing import cast
from pyjs.web.html import {interface} as Control
from pyjs.web.domx import span
def project(value: object) -> Control:
    return cast(Control, value)
def main() -> int:
    project(span())
    return 0
''')
