import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_fixed_tuple_builders_evaluate_later_arguments_before_nullable_failure(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import div, span, tag
from pyjs.web.ssr import render_html
def observe(events: list[int], fail: bool = False) -> str:
    events.append(1)
    gc_collect()
    if fail:
        raise ValueError("argument first")
    return "after"
def main() -> str:
    child: Element = span("child")
    result = ""
    for mode in range(3):
        events: list[int] = []
        target = div("old")
        try:
            if mode == 0:
                target = div(*(None, "last"), observe(events))
            elif mode == 1:
                tag(target, *(child, None, "last"), observe(events))
            else:
                tag(target, *(child, None), observe(events, True))
        except TypeError as error:
            result += "type:" + str(error)
        except ValueError as error:
            result += str(error)
        else:
            return "missing error"
        assert events == [1]
        result += render_html(target)
        target.append("retry")
        result += render_html(target)
    return result
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_fixed_tuple_snapshots_retain_late_attributes_proxies_and_multiple_expansions(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ProxyElement, div, span, tag
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    pass
def parts(attrs: dict[str, str], child: ProxyElement) -> tuple[dict[str, str], str, ProxyElement]:
    return (attrs, "middle", child)
def change(attrs: dict[str, str], child: ProxyElement) -> str:
    attrs["title"] = "late<&"
    child.element = span("replacement")
    gc_collect()
    return "after"
def build(target: Element, attrs: dict[str, str], child: ProxyElement) -> str:
    args = parts(attrs, child)
    tag(target, *(), *args, change(attrs, child), *("one", "two"))
    return render_html(target) + render_html(div(*args))
def main() -> str:
    gc_set_threshold(1)
    attrs = {"title": "early"}
    proxy = ProxyElement()._hydrate(div("old"))
    return build(div(), attrs, proxy) + build(Panel(), attrs, proxy)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_fixed_tuple_forwards_through_typed_builder_pack_without_mutation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, span, tag, tw
from pyjs.web.ssr import render_html
def apply(target: Element, *values: dict[str, str] | Element | str) -> str:
    tag(target, *values)
    gc_collect()
    return render_html(target) + render_html(div(*values))
def main() -> str:
    gc_set_threshold(1)
    target = div({"title": "old", "class": "saved"}, "old")
    values = ({"title": "new"}, tw("changed"), span("<child>"), "end")
    return apply(target, *values)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_untyped_forwarding_uses_checked_dom_arguments(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import div
from pyjs.web.ssr import render_html
def forwarded(*values):
    gc_collect()
    return div(*values)
def main() -> str:
    gc_set_threshold(1)
    return render_html(forwarded({"title": "new<&"}, div("child"), "text"))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("builder", [
    "div(document, {args})", "span(document, {args})", "paragraph(document, {args})",
    "tag(document, 'section', {args})", "document.element('section', {args})",
])
@pytest.mark.parametrize("arguments", ["value", "*(value,)", "*[value]"])
@pytest.mark.parametrize("value", ["Rec('x')", "span(document, 'child')"])
def test_low_level_builders_reject_erased_arguments_before_ir_compilation(builder, arguments, value):
    # These wrappers are not the opaque web DOM ABI. Both invalid application
    # children and valid-but-erased native children retain a clean capability
    # diagnostic, regardless of direct, fixed-tuple or iterable forwarding.
    with pytest.raises(LLVMUnsupported, match="LLVM native argument object is not supported"):
        transpile_llvm(f'''
from pyjs.native import Document, div, span, paragraph, tag
class Rec:
    def __init__(self, text: str):
        self.text = text
def main() -> str:
    document = Document()
    value: object = {value}
    return document.render({builder.format(args=arguments)})
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_fixed_tuple_native_attributes_keep_their_payload_kind(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import Document, attr, div, span
def main() -> str:
    document = Document()
    values = (attr("title", "<&>"), "first", span(document, "child"))
    return document.render(div(document, *values, *(), "last"))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_fixed_tuple_pack_allocation_failures_leave_existing_dom_intact(tmp_path, optimize):
    source = transpile_llvm('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import ProxyElement, div, tag
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm, remaining
def main() -> int:
    gc_set_threshold(1)
    child = ProxyElement()._hydrate(div("child"))
    attrs = {"title": "new"}
    values = (attrs, "text", child)
    stage = 0
    stages = 1
    while stage <= stages:
        target = div("old")
        caught = False
        arm(1000 if stage == 0 else stage)
        try:
            tag(target, *values)
        except MemoryError:
            caught = True
        if stage == 0:
            stages = 1000 - remaining()
        arm(0)
        assert stages > 0
        assert caught == (stage != 0)
        gc_collect()
        if caught:
            assert render_html(target) == "<div>old</div>"
            tag(target, *values)
        assert render_html(target) == '<div title="new">oldtext<div>child</div></div>'
        assert attrs["title"] == "new"
        assert render_html(child.element) == "<div>child</div>"
        stage += 1
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""
