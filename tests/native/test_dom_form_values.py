import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_conditional_source_workarounds_preserve_aliases_and_lazy_effects(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
from pyjs.web.ssr import render_html
def source(events: list[str], label: str) -> list[int]:
    events.append(label)
    return [1, 2]
def build(flag: bool) -> str:
    controls = [input()]
    controls[0].value = "kept"
    copied: list[Element] = list(controls) if flag else [div("fresh")]
    copied.append(div("tail"))
    assert len(controls) == 1
    assert controls[0].value == "kept"
    assert (copied[0] is controls[0]) == flag
    events: list[str] = []
    generated: list[Element] = (
        list(input() for _ in source(events, "left")) if flag
        else list(div(str(i)) for i in source(events, "right")))
    comprehended: list[Element] = (
        [input() for _ in source(events, "left2")] if flag
        else [div(str(i)) for i in source(events, "right2")])
    assert events == (["left", "left2"] if flag else ["right", "right2"])
    return render_html(div(*copied, *generated, *comprehended)) + str(events)
def main() -> str:
    return build(True) + build(False)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("builder", ["input", "textarea", "button"])
def test_live_form_value_is_distinct_from_serialized_attributes(tmp_path, optimize, builder):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import {builder}
from pyjs.web.ssr import render_html
def main() -> str:
    gc_set_threshold(1)
    control = {builder}({{"value": "initial"}})
    assert control.value == ""
    alias = control
    control.value = "live<&" + str(3)
    gc_collect()
    retained = alias.value
    alias.setAttribute("value", "attribute")
    assert control.value == "live<&3"
    before = render_html(control)
    alias.value = ""
    control.removeAttribute("value")
    control.append("child")
    control.replaceChildren("replacement")
    gc_collect()
    assert control.value == ""
    return retained + before + render_html(control)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_typed_form_reference_and_application_value_fields(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import CustomElement, input, ref, tag
from pyjs.web.ssr import render_html
class Search(CustomElement):
    query: HTMLInputElement
    def __init__(self):
        super().__init__()
        self.value = 42
        self.query = ref(input({"value": "initial"}))
        tag(self, self.query)
        self.query.value = "live"
def view(value: HTMLInputElement | None) -> Element | None:
    return value
def change(value: HTMLInputElement, text: str) -> None:
    gc_collect()
    value.value = text
def read(value: HTMLInputElement | str) -> str:
    return value if isinstance(value, str) else value.value
def main() -> str:
    search = Search()
    assert view(search.query) is search.query
    assert view(None) is None
    values: list[HTMLInputElement] = [search.query]
    change(values[0], "changed")
    assert search.query.value == "changed"
    assert read(search.query) == "changed"
    assert read("literal") == "literal"
    assert search.value == 42
    return render_html(search)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert 'value="initial"' in result.native.stdout
    assert "changed" not in result.native.stdout
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_form_unions_preserve_custom_property_dispatch(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import CustomElement, input
class Box(CustomElement):
    def __init__(self):
        super().__init__()
        self.text = "box"
    @property
    def value(self) -> str:
        gc_collect()
        return self.text
    @value.setter
    def value(self, text: str) -> None:
        gc_collect()
        self.text = "box:" + text
def read(value: HTMLInputElement | Box) -> str:
    return value.value
def widen(value: Box | str) -> HTMLInputElement | Box | str:
    return value
def optional(value: Box | None) -> HTMLInputElement | Box | None:
    return value
def main() -> str:
    gc_set_threshold(1)
    box = Box()
    control = input()
    alias: HTMLInputElement | Box = box
    assert read(box) == "box"
    assert alias.value == "box"
    assert read(control) == ""
    widened = widen(box)
    if isinstance(widened, str):
        return "wrong string"
    else:
        assert widened.value == "box"
    assert widen("literal") == "literal"
    present = optional(box)
    if present is None:
        return "wrong None"
    else:
        assert present.value == "box"
    assert optional(None) is None
    values: list[HTMLInputElement | Box] = [control, box]
    output = ""
    for value in values:
        value.value = "written" + str(len(output))
        gc_collect()
        output += value.value + "/"
    assert alias.value == box.value
    return output + read(box) + "/" + read(control)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_plain_elements_do_not_gain_form_value_properties():
    with pytest.raises(CompilationError):
        transpile_llvm('''
from pyjs.web.domx import div
def main() -> str:
    return div().value
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_form_and_ordinary_dom_joins_share_opaque_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement, HTMLDivElement, HTMLButtonElement
from pyjs.web.domx import CustomElement, input, div, button
from pyjs.web.ssr import render_html
class Box(CustomElement):
    def __init__(self):
        super().__init__()
        self.append("box")
def field(editable: bool) -> Element:
    return input() if editable else div("read-only")
def annotated(editable: bool) -> Element:
    node: Element = div("annotation") if editable else input()
    return node
def text(node: HTMLInputElement | HTMLDivElement) -> str:
    gc_collect()
    node.setAttribute("title", "mixed")
    return node.textContent
def nullable(node: HTMLInputElement | Element | None) -> str:
    if node is None:
        return "absent"
    return node.textContent
def sibling(node: HTMLInputElement | CustomElement) -> str:
    return node.textContent
def main() -> str:
    gc_set_threshold(1)
    result = field(True).textContent + field(False).textContent
    result += annotated(True).textContent + annotated(False).textContent
    control = input()
    control.value = "live"
    other = div("other")
    values = [control, other]
    for value in values:
        result += text(value) + "/"
    buttons: list[HTMLButtonElement | HTMLDivElement] = [button("button"), div("div")]
    for item in buttons:
        result += item.textContent + "/"
    result += nullable(control) + nullable(other) + nullable(None)
    result += sibling(control) + sibling(Box())
    assert values[0] is control
    assert values[1] is other
    assert control.value == "live"
    return result + render_html(div(*values))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("definition", ['value: str = "box"', 'value = state("")'])
def test_form_union_requires_compatible_application_property(definition):
    with pytest.raises(CompilationError, match="has incompatible definitions"):
        transpile_llvm('''
from pyjs import state
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import CustomElement, input
class Box(CustomElement):
    DEFINITION
def read(value: HTMLInputElement | Box) -> str:
    return value.value
def main() -> str:
    return read(input()) + read(Box())
'''.replace("DEFINITION", definition))


@pytest.mark.parametrize("optimize", [0, 2])
def test_fresh_nested_form_literals_infer_common_dom_layout(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import input, div, textarea
def main() -> str:
    gc_set_threshold(1)
    control = input()
    control.value = "live"
    rows = [("name", control), ("note", div("n"))]
    output = ""
    for key, node in rows:
        gc_collect()
        output += key + "=" + node.textContent + ";"
    grid = [[input(), textarea()], [div("a")]]
    for row in grid:
        for node in row:
            output += node.textContent + ","
    groups = {"edit": [input()], "view": [div("v")]}
    for key in groups:
        for node in groups[key]:
            output += key + node.textContent
    for enabled in [True, False]:
        values = [input()] if enabled else [div("d")]
        pair = (input(), 1) if enabled else (div("t"), 2)
        mapping = {"k": input()} if enabled else {"k": div("m")}
        gc_collect()
        output += values[0].textContent + pair[0].textContent + str(pair[1])
        output += mapping["k"].textContent
    typed: list[tuple[str, HTMLInputElement]] = [("typed", input())]
    typed[0][1].value = "kept"
    assert rows[0][1] is control
    return output + control.value + typed[0][1].value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_nested_dom_join_does_not_widen_aliased_form_lists():
    with pytest.raises(LLVMUnsupported, match="collection views require matching concrete item storage and element types"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
def mutate(rows: list[list[Element]]) -> None:
    rows[0].append(div())
def main() -> str:
    controls = [input()]
    mutate([controls, [div()]])
    return controls[0].value
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_literals_join_conditional_dom_leaves(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.domx import input, div
def make(enabled: bool) -> str:
    rows = [("a", input() if enabled else div("c")), ("b", div("b"))]
    grid = [[input() if enabled else div("c")], [div("b")]]
    result = ""
    gc_collect()
    for label, node in rows:
        result += label + node.textContent
    for row in grid:
        for node in row:
            result += node.textContent
    return result
def main() -> str:
    return make(True) + "|" + make(False)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_form_collection_copies_widen_items_not_source_aliases(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import CustomElement, input, div
from pyjs.web.ssr import render_html
class Box(CustomElement):
    def __init__(self):
        super().__init__()
        self.textContent = "box"
        self.value = 42
def compose(controls: list[HTMLInputElement]) -> list[Element]:
    header: list[Element] = [div("header")]
    result = header + controls
    result.extend(controls)
    result += controls
    result[0:1] = controls
    result.extend([input() for _ in range(2)])
    gc_collect()
    return result
def main() -> str:
    gc_set_threshold(1)
    control = input()
    control.value = "live"
    controls = [control]
    result = compose(controls)
    result.append(div("tail"))
    assert len(controls) == 1
    assert controls[0] is control
    assert result[0] is control
    result[0] = div("replaced")
    assert controls[0].value == "live"
    box = Box()
    result.extend([box])
    gc_collect()
    assert result[-1] is box
    assert box.value == 42
    return render_html(div(*result)) + controls[0].value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_fresh_form_comprehensions_and_constructors_use_destination_type(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import input, textarea, div
from pyjs.web.ssr import render_html
class Panel:
    def __init__(self):
        self.nodes: list[Element] = []
    @property
    def items(self) -> list[Element]:
        return self.nodes
    @items.setter
    def items(self, value: list[Element]) -> None:
        self.nodes = value
def fields() -> list[Element]:
    return [textarea() for _ in range(2)]
def copy(controls: list[HTMLInputElement]) -> list[Element]:
    return list(controls)
def use(nodes: list[Element]) -> str:
    nodes.append(div("tail"))
    gc_collect()
    return render_html(div(*nodes))
def main() -> str:
    gc_set_threshold(1)
    controls = [input(), input()]
    controls[0].value = "live"
    direct: list[Element] = [input() for _ in range(2)]
    selected: list[Element] = [c for c in controls]
    constructed: list[Element] = list(controls)
    generated: list[Element] = list(input() for _ in range(2))
    reverse: list[Element] = list(reversed(controls))
    mixed: list[Element] = [input() if flag else div("view") for flag in [True, False]]
    assert selected[0] is controls[0]
    selected[0] = div("replaced")
    output = use(direct) + use(selected) + use(constructed)
    output += use(generated) + use(reverse) + use(mixed) + use(fields()) + use(copy(controls))
    output += use([input() for _ in range(2)]) + use(list(controls))
    panel = Panel()
    panel.nodes = [input() for _ in range(2)]
    output += use(panel.nodes)
    panel.nodes = list(controls)
    output += use(panel.nodes)
    panel.items = [c for c in controls]
    output += use(panel.items)
    panel.items = list(controls)
    output += use(panel.items) + use([*controls, *direct])
    gc_collect()
    assert len(controls) == 2
    return output + controls[0].value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("rows", [
    "[[input() for j in range(2)] for i in range(2)]",
    "[list(input() for j in range(2)) for i in range(2)]",
    "[[input()] for i in range(2)]",
    "list([input() for j in range(2)] for i in range(2))",
])
def test_nested_fresh_dom_lists_receive_late_field_types(tmp_path, optimize, rows):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
from pyjs.web.ssr import render_html
class Grid:
    def __init__(self):
        self.rows: list[list[Element]] = []
        self.row: list[Element] = []
def fill(grid: Grid, enabled: bool) -> None:
    grid.rows = {rows}
    grid.row = [input() for i in range(2)] if enabled else [div("view")]
def main() -> str:
    grid = Grid()
    result = ""
    for enabled in [True, False]:
        fill(grid, enabled)
        grid.rows[0].append(div("nested"))
        grid.row.append(div("tail"))
        gc_collect()
        result += render_html(div(*grid.rows[0], *grid.row))
    return result
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_form_lambda_parameters_keep_resolved_type_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from typing import Callable
from pyjs.native import gc_collect
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import input
def main() -> str:
    controls = [input(), input()]
    controls[1].value = "long"
    read: Callable[[HTMLInputElement], str] = lambda node: node.value + "!"
    ordered = sorted(controls, key=lambda node: len(node.value))
    copied = list(map(lambda node: node, ordered))
    selected = list(filter(lambda node: node.value != "", copied))
    gc_collect()
    assert selected[0] is controls[1]
    return read(selected[0]) + max(controls, key=lambda node: len(node.value)).value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("rows", [
    "[[(int8(127), input()) for j in range(2)] if flag else [(int8(4), div('other'))] for i in range(2)]",
    "list([(int8(127), input()) for j in range(2)] if flag else [(int8(4), div('other'))] for i in range(2))",
    "list([[(int8(127), input())] if flag else [(int8(4), div('other'))] for i in range(2)])",
])
def test_nested_fresh_dom_destinations_refresh_numeric_representations(tmp_path, optimize, rows):
    result = LLVM().assert_matches_python(f'''
from pyjs import int8
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
from pyjs.web.ssr import render_html
class Grid:
    def __init__(self):
        self.rows: list[list[tuple[int8, Element]]] = []
def fill(grid: Grid, flag: bool):
    grid.rows = {rows}
def main() -> str:
    grid = Grid()
    result = ""
    for flag in [True, False]:
        fill(grid, flag)
        grid.rows[0].append((int8(126), div("tail")))
        gc_collect()
        for row in grid.rows:
            for number, element in row:
                result += str(number + int8(1)) + render_html(element)
    return result
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("items", [
    "((int8(127), first), (int8(4), div('other')))",
    "((int8(127), first), (int8(4), input()))",
    "((int8(127), first),)",
])
def test_list_of_fresh_tuple_records_receives_dom_destination(tmp_path, optimize, items):
    result = LLVM().assert_matches_python(f'''
from pyjs import int8
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
from pyjs.web.ssr import render_html
def main() -> str:
    first = input()
    first.value = "live"
    rows: list[tuple[int8, Element]] = list({items})
    rows.append((int8(126), div("tail")))
    gc_collect()
    assert rows[0][1] is first and first.value == "live"
    return "".join(str(number + int8(1)) + render_html(node) for number, node in rows)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [
    "((int8(127), make(events, 'yes')),) if flag else ((int8(3), make(events, 'no')),)",
    "(((int8(127), make(events, 'yes')),) if flag else ((int8(3), make(events, 'no')),)) if outer(events) else ((int8(9), make(events, 'dead')),)",
    "[(int8(127), make(events, 'yes'))] if flag else [(int8(3), make(events, 'no'))]",
    "((int8(127), make(events, 'yes')) for i in range(1)) if flag else ((int8(3), make(events, 'no')) for i in range(1))",
])
def test_list_item_destinations_follow_conditional_source_shapes(tmp_path, optimize, source):
    result = LLVM().assert_matches_python(f'''
from pyjs import int8
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import input, div
from pyjs.web.ssr import render_html
def outer(events: list[str]) -> bool:
    events.append("outer")
    return True
def make(events: list[str], label: str) -> HTMLInputElement:
    events.append(label)
    gc_collect()
    return input()
def build(flag: bool) -> str:
    events: list[str] = []
    rows: list[tuple[int8, Element]] = list({source})
    assert events[-1] == ("yes" if flag else "no")
    assert len(events) == (2 if events[0] == "outer" else 1)
    rows.append((int8(126), div("tail")))
    gc_collect()
    return "".join(str(number + int8(1)) + render_html(node) for number, node in rows)
def main() -> str:
    return build(True) + build(False)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", ["list(records)", "list(row for row in records)"])
def test_existing_dom_tuple_records_keep_their_field_layout(expression):
    with pytest.raises(LLVMUnsupported, match="tuple views require matching concrete item storage"):
        transpile_llvm(f'''
from pyjs import int8
from pyjs.web.dom import Element
from pyjs.web.domx import input
def main() -> int:
    records = ((int8(127), input()),)
    rows: list[tuple[int8, Element]] = {expression}
    return len(rows)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_existing_dom_tuple_records_can_be_explicitly_rebuilt(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import int8
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
from pyjs.web.ssr import render_html
def main() -> str:
    control = input()
    records = ((int8(127), control),)
    rows: list[tuple[int8, Element]] = [(number, node) for number, node in records]
    indexed: list[tuple[int, Element]] = [(i, node) for i, node in enumerate([control])]
    zipped: list[tuple[int, Element]] = [(i, node) for i, node in zip([1], [control])]
    rows.append((int8(126), div("tail")))
    assert rows[0] is not records[0] and rows[0][1] is control
    return str(rows[0][0] + int8(1)) + render_html(div(rows[1][1], indexed[0][1], zipped[0][1]))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_dom_record_alternatives_preserve_layout_and_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import int8
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
from pyjs.web.ssr import render_html
def main() -> str:
    control = input()
    records = ((int8(127), control), (int8(4), div("other")))
    rebuilt: list[tuple[int8, Element]] = [
        (records[0][0], records[0][1]), (records[1][0], records[1][1])]
    declared: tuple[tuple[int8, Element], ...] = ((int8(127), control), (int8(4), div("other")))
    copied: list[tuple[int8, Element]] = list(declared)
    listed = [(int8(127), control), (int8(4), div("other"))]
    assert rebuilt[0] is not records[0] and rebuilt[0][1] is control
    assert copied[0] is declared[0] and copied[0][1] is control
    union_rows: list[tuple[int8, Element] | Element] = [(int8(127), control), div("union")]
    assert len(union_rows) == 2
    return "".join(str(number + int8(1)) + render_html(node) for number, node in rebuilt + copied + listed)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dom_literal_joins_preserve_represented_sibling_fields(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import StaticArray, int8
from pyjs.web.domx import input, div
def main() -> str:
    rows = [(int8(127), input()), (int8(4), div("row"))]
    output = ""
    for number, node in rows:
        output += str(number + int8(1)) + node.textContent
    arrays = [(StaticArray[int8, 1]([127]), input()),
              (StaticArray[int8, 1]([3]), div("array"))]
    for numbers, node in arrays:
        output += str(numbers[0] + int8(1)) + node.textContent
    for enabled in [True, False]:
        pair = (int8(127), input()) if enabled else (int8(3), div("pair"))
        grid = [[(int8(127), input())], [(int8(5), div("grid"))]]
        output += str(pair[0] + int8(1)) + pair[1].textContent
        for group in grid:
            for number, node in group:
                output += str(number + int8(1)) + node.textContent
    return output
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", [
    '[(int8(1), input()), (int16(2), div())]',
    '((int8(1), input()) if True else (int16(2), div()))',
])
def test_dom_literal_join_rejects_incompatible_sibling_representations(expression):
    with pytest.raises(CompilationError, match="incompatible nested representations"):
        transpile_llvm(f'''
from pyjs import int8, int16
from pyjs.web.domx import input, div
def main() -> int:
    values = {expression}
    return len(values)
''')


@pytest.mark.parametrize("operation", [
    "controls.extend(elements)", "controls += elements",
    "controls = controls + elements", "controls[:] = elements",
])
def test_collection_copy_cannot_narrow_elements_to_form_controls(operation):
    with pytest.raises(CompilationError, match="WebFormControl.*WebElement"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import div, input
def main() -> str:
    controls: list[HTMLInputElement] = [input()]
    elements: list[Element] = [div()]
    {operation}
    return controls[0].value
''')


def test_contextual_list_constructor_does_not_retype_shadowed_alias_factory():
    with pytest.raises(LLVMUnsupported, match="collection views require matching concrete item storage and element types"):
        transpile_llvm('''
from builtins import list as List
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import input, div
def list(values: List[HTMLInputElement]) -> List[HTMLInputElement]:
    return values
def main() -> str:
    controls = [input()]
    values: List[Element] = list(controls)
    values.append(div())
    return controls[0].value
''')


@pytest.mark.parametrize("expression", [
    "[controls] if enabled else [[input()]]",
    "[[input()] if enabled else controls]",
    "[controls for _ in range(2)]",
    "list(controls for _ in range(2))",
    "list((controls,))",
    "list((controls,) if enabled else ([input()],))",
])
def test_late_nested_or_conditional_typing_preserves_source_list_aliases(expression):
    with pytest.raises(LLVMUnsupported, match="collection views require matching|unions cannot distinguish"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import input, div
class Grid:
    def __init__(self):
        self.rows: list[list[Element]] = []
def build(enabled: bool) -> str:
    controls = [input()]
    grid = Grid()
    grid.rows = {expression}
    grid.rows[0][0] = div()
    return controls[0].value
def main() -> str:
    return build(True)
''')


def test_mutable_form_collection_cannot_widen_to_arbitrary_elements():
    with pytest.raises(LLVMUnsupported, match="collection views require matching concrete item storage and element types"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import div, input
def replace(values: list[Element]) -> None:
    values[0] = div()
def main() -> str:
    controls: list[HTMLInputElement] = [input()]
    replace(controls)
    return controls[0].value
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_failed_value_copy_leaves_previous_live_value(tmp_path, optimize):
    source = transpile_llvm('''
from pyjs.native import gc_collect
from pyjs.web.domx import input
from tests.native.allocation_support import arm
def main() -> int:
    failures = 0
    for point in range(1, 8):
        control = input({"value": "attribute"})
        control.value = "old"
        replacement = "new" * 5000
        gc_collect()
        arm(point)
        try:
            control.value = replacement
        except MemoryError:
            arm(0)
            failures += 1
            assert control.value == "old"
            control.value = replacement
        arm(0)
        gc_collect()
        assert control.value == replacement
        assert control.getAttribute("value") == "attribute"
    assert 0 < failures < 7
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_live_value_assignment_keeps_rhs_then_receiver_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.html import HTMLInputElement
from pyjs.web.domx import input
def receiver(value: HTMLInputElement, log: list[str]) -> HTMLInputElement:
    log.append("receiver")
    gc_collect()
    return value
def argument(log: list[str], fail: bool) -> str:
    log.append("argument")
    gc_collect()
    if fail:
        raise ValueError("rhs")
    return "new" + str(len(log))
def main() -> str:
    control = input()
    log: list[str] = []
    receiver(control, log).value = argument(log, False)
    try:
        receiver(control, log).value = argument(log, True)
    except ValueError:
        log.append("caught")
    return repr(log) + control.value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
