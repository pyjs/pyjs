import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True])
def test_clearing_text_needs_no_allocation_and_preserves_aliases(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
from pyjs.native import gc_collect
from pyjs.web.domx import div, span
from pyjs.web.dom import Element
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm, remaining

def clear(item: Element, value: str | None) -> None:
    item.textContent = value

def main() -> int:
    {"gc_collect()" if managed else "pass"}
    child = span("old")
    for mode in range(3):
        item = div({{"title": "kept"}}, child, "tail")
        alias = item
        for index in range(8):
            item.setAttribute(str(index), "kept")
        empty = "computed"[8:]
        arm(1)
        if mode == 0:
            clear(item, "")
        elif mode == 1:
            clear(item, empty)
        else:
            clear(item, None)
        untouched = remaining()
        arm(0)
        assert untouched == 1 and alias.textContent == ""
        assert item.getAttribute("title") == "kept" and child.textContent == "old"
        for index in range(8):
            assert item.getAttribute(str(index)) == "kept"
        item.append(child)
        assert item.textContent == "old" and render_html(child) == "<span>old</span>"
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_content_reads_and_replaces_owned_children(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, span, tag
from pyjs.web.ssr import render_html

def replace(item: Element, value: str | None) -> str:
    before = item.textContent
    item.textContent = value
    gc_collect()
    return before + ":" + item.textContent + ":" + render_html(item)

def main() -> str:
    gc_set_threshold(1)
    child = span("nested<&😀")
    item = div({"title": "kept"}, "first", child, "tail")
    old = item.textContent
    changed = replace(item, "new<&")
    child.textContent = "retained"
    item.append(child)
    empty = replace(item, None)
    void = tag("input", "temporary")
    void.textContent = ""
    return old + changed + empty + render_html(child) + render_html(void)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_text_property_and_super_getter(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html

class Item(CustomElement):
    @property
    def textContent(self) -> str:
        return "prefix:" + super().textContent

    @textContent.setter
    def textContent(self, value: str | None) -> None:
        self.replaceChildren("cleared" if value is None else value)

def main() -> str:
    item = Item()
    item.textContent = "new<&"
    before = item.textContent
    item.textContent = None
    return before + ":" + item.textContent + ":" + render_html(item)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_opaque_text_property_cannot_skip_a_custom_getter():
    with pytest.raises(LLVMUnsupported, match="textContent overrides"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    @property
    def textContent(self) -> str:
        return "overridden"

def read(item: Element) -> str:
    return item.textContent

def main() -> str:
    return read(Item())
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_assignment_orders_operands_and_roots_rhs(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement, div
from pyjs.web.ssr import render_html

class Item(CustomElement):
    pass

def replacement(events: list[str], fail: bool) -> str:
    events.append("rhs")
    if fail:
        raise ValueError("failed")
    return "new<&" + str(len(events))

def owner(item: Item, events: list[str]) -> Item:
    events.append("owner")
    item.replaceChildren("receiver change")
    gc_collect()
    return item

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    item = Item()
    item.append("old")
    try:
        owner(item, events).textContent = replacement(events, True)
    except ValueError:
        events.append(item.textContent)
    owner(item, events).textContent = replacement(events, False)
    # Augmented assignment reads before its RHS, even when receiver callbacks
    # changed the tree; the final setter uses that captured text exactly once.
    owner(item, events).textContent += replacement(events, False)
    optional = div("optional") if len(events) else None
    if optional is not None:
        optional.textContent = item.textContent
        return render_html(optional) + str(events)
    return "missing"
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_property_in_mixed_receiver_and_result_union(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import div

class Count:
    def __init__(self):
        self.saved = 0
    @property
    def textContent(self) -> int:
        return self.saved
    @textContent.setter
    def textContent(self, value: str | None) -> None:
        self.saved = 0 if value is None else len(value)

def read(item: Element | Count) -> str | int:
    return item.textContent

def main() -> str:
    items: list[Element | Count] = [div("before"), Count()]
    results: list[str | int] = []
    for item in items:
        item.textContent = "new<&"
        results.append(read(item))
        item.textContent = None
        results.append(read(item))
    gc_collect()
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_content_deep_tree_and_retained_result(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.domx import div

def main() -> str:
    item = div("deep<&😀")
    for index in range(5000):
        item = div(item)
    retained = item.textContent
    item.textContent = "replacement"
    gc_collect()
    return retained + ":" + item.textContent
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_text_allocation_failure_preserves_tree_and_can_retry(tmp_path, optimize, operation):
    source = transpile_llvm(f'''
from pyjs.native import gc_collect
from pyjs.web.domx import div, span
from tests.native.allocation_support import arm

def main() -> int:
    failures = 0
    for point in range(1, 45):
        old = "é<&😀" * 4000
        new = "replacement" + str(point)
        item = div({{"title": "kept"}}, span(old))
        failed = False
        arm(point)
        try:
            {"result = item.textContent" if operation == "read" else "item.textContent = new"}
        except MemoryError:
            arm(0)
            failed = True
        arm(0)
        gc_collect()
        if failed:
            failures += 1
        assert item.textContent == {"old" if operation == "read" else "(old if failed else new)"}
        assert item.getAttribute("title") == "kept"
        item.textContent = "retry"
        assert item.textContent == "retry"
    assert failures > 0
    assert failures < 44
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""
