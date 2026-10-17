"""Browser-only hooks and statically known controls in native SSR."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_listener_callbacks_are_not_native_reachable(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement, div, input, ref, tag
from pyjs.web.events import Event
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.search = ref(input())
        self.search.addEventListener('input', self.browser_callback, passive=True)
        self.addEventListener('click', self.browser_callback, once=True)
        self.append(self.search)
    def browser_callback(self, event: Event) -> None:
        # Interactive browser APIs are intentionally outside native SSR.
        self.search.focus()
        event.preventDefault()
def main() -> str:
    panel = Panel()
    plain = div('label')
    plain.addEventListener('click', panel.browser_callback, capture=True)
    return render_html(tag(panel, plain))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert "browser_callback" not in comparison.native.llvm_ir


def test_listener_erasure_omits_receiver_and_argument_evaluation(tmp_path):
    result = LLVM().run_source('''
from pyjs.web.html import HTMLDivElement
from pyjs.web.domx import div
def receiver(log: list[str]) -> HTMLDivElement:
    log.append('receiver')
    return div()
def browser_only() -> object:
    return {1} + 2
def main() -> str:
    log: list[str] = []
    receiver(log).addEventListener('click', browser_only(), signal=browser_only())
    return repr(log)
''', directory=tmp_path)
    assert result.returncode == 0
    assert result.stdout == "[]"
    assert result.stderr == ""
    assert "fn.browser_only" not in result.llvm_ir


def test_concrete_listener_override_keeps_its_python_body(tmp_path):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def addEventListener(self, type: str, callback: object, *, once: bool = False) -> None:
        super().addEventListener(type, callback, once=once)
        CustomElement.addEventListener(self, 'ignored', callback)
        self.setAttribute('data-event', type)
def main() -> str:
    panel = Panel()
    panel.addEventListener('change', None, once=True)
    return render_html(panel)
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("receiver_type", ["Base", "CustomElement", "Element"])
@pytest.mark.parametrize("receiver", ["value", "identity(value)", "[value][0]"])
def test_erased_listener_rejects_reached_overrides(receiver_type, receiver):
    with pytest.raises(LLVMUnsupported, match="addEventListener overrides require a concrete"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Base(CustomElement):
    pass
def identity(value: {receiver_type}) -> {receiver_type}:
    return value
def register(value: {receiver_type}) -> None:
    {receiver}.addEventListener('change', None)
class Child(Base):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
def main() -> int:
    register(Child())
    return 0
''')


@pytest.mark.parametrize("body", [
    "self.addEventListener('initial', None)",
    "if True:\n    self.addEventListener('initial', None)",
    "ignored = self.addEventListener('initial', None) is None",
    "return self.addEventListener('initial', None)",
])
def test_erased_listener_checks_survive_branches_values_and_inherited_constructors(body):
    body = body.replace("\n", "\n        ")
    with pytest.raises(LLVMUnsupported, match="addEventListener overrides require a concrete"):
        transpile_llvm(f'''
from pyjs.web.domx import CustomElement
class Base(CustomElement):
    def __init__(self):
        super().__init__()
        {body}
class Child(Base):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
def main() -> int:
    Child()
    return 0
''')


def test_erased_listener_does_not_reject_unrelated_application_overrides(tmp_path):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Plain(CustomElement):
    def __init__(self):
        super().__init__()
        self.addEventListener('click', None)
class Other(CustomElement):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
def main() -> str:
    other = Other()
    other.addEventListener('change', None)
    return render_html(Plain()) + render_html(other)
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("member", ["field", "property"])
def test_erased_listener_checks_attribute_receivers(member):
    declaration = (
        "    def __init__(self, child: Element):\n        self.element: Element = child"
        if member == "field" else
        "    @property\n    def element(self) -> Element:\n        return Child()"
    )
    construction = "Holder(Child())" if member == "field" else "Holder()"
    with pytest.raises(LLVMUnsupported, match="addEventListener overrides require a concrete"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Child(CustomElement):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
class Holder:
{declaration}
def main() -> int:
    holder = {construction}
    holder.element.addEventListener('change', None)
    return 0
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_unrelated_overrides_do_not_block_form_or_union_listeners(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import cast
from pyjs.web.domx import CustomElement, div, input, tag
from pyjs.web.html import HTMLInputElement, HTMLSelectElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
class Left(CustomElement):
    pass
class Right(CustomElement):
    pass
def register_form(control: HTMLSelectElement) -> None:
    control.addEventListener('change', None)
def register_forms(control: HTMLInputElement | HTMLSelectElement) -> None:
    control.addEventListener('input', None)
def register_nodes(node: Left | Right) -> None:
    node.addEventListener('click', None)
def main() -> str:
    panel = Panel()
    panel.addEventListener('custom', None)
    control = tag('select')
    control.addEventListener('change', None)
    field = input()
    field.addEventListener('input', None)
    register_form(control)
    register_forms(control)
    register_forms(field)
    left = Left()
    right = Right()
    register_nodes(left)
    register_nodes(right)
    Left().addEventListener('unused', None)
    input().addEventListener('unused', None)
    tag('select').addEventListener('unused', None)
    cast(Left, left).addEventListener('unused', None)
    return render_html(div(panel, control, field, left, right))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_form_subclass_listener_override_is_still_applicable():
    with pytest.raises(LLVMUnsupported, match="addEventListener overrides require a concrete"):
        transpile_llvm('''
from pyjs.web.html import HTMLSelectElement
class MySelect(HTMLSelectElement):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
def register(control: HTMLSelectElement) -> None:
    control.addEventListener('change', None)
def main() -> int:
    register(MySelect())
    return 0
''')


@pytest.mark.parametrize("target", ["HTMLSelectElement", "Left | Right"])
@pytest.mark.parametrize("receiver", ["cast(TARGET, panel)", "[cast(TARGET, panel)][0]", "converted(panel)"])
def test_erased_listener_does_not_hide_invalid_receiver_casts(target, receiver):
    receiver = receiver.replace("TARGET", target)
    # Direct casts get their precise diagnostic. Hidden casts require binding
    # the receiver instead of a second analysis of erased helper/protocol code.
    helper = (f"def converted(panel: Panel) -> {target}: return cast({target}, panel)\n"
              if receiver == "converted(panel)" else "")
    diagnostic = ("concrete casts require matching types" if receiver.startswith("cast(")
                  else "bind the checked receiver first")
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm('''
from typing import cast
from pyjs.web.domx import CustomElement
from pyjs.web.html import HTMLSelectElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
class Left(CustomElement):
    pass
class Right(CustomElement):
    pass
''' + helper + f'''
def main() -> str:
    panel = Panel()
    {receiver}.addEventListener('change', None)
    return render_html(panel)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_listener_accepts_identity_casts_and_application_upcasts(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import cast
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.dom import Element
from pyjs.web.html import HTMLSelectElement
from pyjs.web.ssr import render_html
class Plain(CustomElement):
    pass
def main() -> str:
    control = tag('select')
    plain = Plain()
    cast(HTMLSelectElement, control).addEventListener('change', None)
    cast(Element, plain).addEventListener('change', None)
    erased: object = plain
    checked = cast(Plain, erased)
    checked.addEventListener('change', None)
    return render_html(div(control, plain))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("receiver", [
    "cast(Left, cast(object, panel))",
    "[cast(Left, cast(object, panel))][0]",
    "converted(panel)",
    "holder.element",
    "as_base(holder).element",
    "forward(converted, panel)",
    "CheckedHolder(panel).element",
])
def test_erased_listener_requires_runtime_casts_to_run_first(receiver):
    with pytest.raises(LLVMUnsupported, match="bind the checked receiver first"):
        transpile_llvm('''
from typing import Callable, cast
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
class Left(CustomElement):
    pass
def converted(value: object) -> Left:
    return cast(Left, value)
class BaseHolder:
    def __init__(self, value: object): self.value = value
    @property
    def element(self) -> Left: return Left()
class Holder(BaseHolder):
    @property
    def element(self) -> Left: return converted(self.value)
class CheckedHolder:
    def __init__(self, value: object): self.element = cast(Left, value)
def as_base(holder: BaseHolder) -> BaseHolder: return holder
def forward(factory: Callable[[object], Left], value: object) -> Left:
    return factory(value)
def main() -> int:
    panel = Panel()
    holder = Holder(panel)
    ''' + receiver + '''.addEventListener('change', None)
    return 0
''')


@pytest.mark.parametrize("base", ["CustomElement", "HTMLDivElement"])
def test_erased_factory_cannot_hide_its_only_overriding_class(base):
    with pytest.raises(LLVMUnsupported, match="addEventListener overrides require a concrete"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.html import HTMLDivElement
class Child({base}):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
def factory() -> Element:
    return Child()
def main() -> int:
    factory().addEventListener('change', None)
    return 0
''')
    # The failed compilation's discovered overrides must not leak to the next
    # program. No callback or factory body is required for genuine erasure.
    transpile_llvm('''
from pyjs.web.domx import div
def main() -> int:
    div().addEventListener('change', None)
    return 0
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_reached_portable_framework_helpers_are_emitted(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import div
from pyjs.web.ssr import render_html
from pyjs.web.ui.separator import Separator
from pyjs.web.ui.skeleton import Skeleton
def main() -> str:
    nodes = [Separator('vertical', decorative=False), Skeleton('8rem', '2rem')]
    nodes.append(Separator())
    return render_html(div(*nodes))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("name", "interface"), [
    ("input", "HTMLInputElement"), ("textarea", "HTMLTextAreaElement"),
    ("button", "HTMLButtonElement"), ("select", "HTMLSelectElement"),
])
def test_literal_tag_controls_keep_live_value_and_safe_casts(tmp_path, optimize, name, interface):
    comparison = LLVM().assert_matches_python(f'''
from typing import cast
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import tag as create, ref
from pyjs.web.html import {interface}
from pyjs.web.ssr import render_html
def main() -> str:
    gc_set_threshold(1)
    control = ref(cast({interface}, create('{name}', {{'value': 'attribute'}})))
    assert control.value == ''
    alias = control
    control.value = 'live<&' + str(3)
    gc_collect()
    assert alias.value == 'live<&3'
    return alias.value + render_html(control)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("expression", ["tag('div')", "tag(name)"])
def test_unknown_tag_shapes_do_not_gain_form_properties(expression):
    with pytest.raises(CompilationError, match="Attribute 'value'.*not defined"):
        transpile_llvm(f'''
from pyjs.web.domx import tag
def main() -> str:
    name = 'select'
    return {expression}.value
''')
    with pytest.raises(LLVMUnsupported, match="concrete casts"):
        transpile_llvm(f'''
from typing import cast
from pyjs.web.domx import tag
from pyjs.web.html import HTMLSelectElement
def main() -> str:
    name = 'select'
    return cast(HTMLSelectElement, {expression}).value
''')


@pytest.mark.parametrize("name", ["input", "textarea", "button", "select"])
def test_svg_form_names_do_not_gain_html_properties(name):
    prefix = f'''
from pyjs.web.domx import svg_tag as create
from pyjs.web.html import HTMLSelectElement
from typing import cast
def main() -> str:
    element = create('{name}')
'''
    with pytest.raises(CompilationError, match="Attribute 'value'.*not defined"):
        transpile_llvm(prefix + "    return element.value\n")
    with pytest.raises(LLVMUnsupported, match="concrete casts"):
        transpile_llvm(prefix + "    return cast(HTMLSelectElement, element).value\n")


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_form_tags_allow_explicit_element_storage_and_svg_siblings(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import div, tag, svg_tag
from pyjs.web.ssr import render_html
class Form:
    def __init__(self):
        self.control: Element = tag('textarea')
def main() -> str:
    form = Form()
    form.control = div('field')
    element: Element = tag('select')
    element = div('local')
    nodes: list[Element] = [tag('input')]
    nodes.append(div('list'))
    return render_html(div(form.control, element, *nodes,
                           svg_tag('button'), svg_tag('select')))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
