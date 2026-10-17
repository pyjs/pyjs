import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("builder", ['div', 'tag'])
def test_new_builders_observe_late_dictionary_mutations(tmp_path, optimize, builder):
    call = 'div(attrs, change(attrs))' if builder == 'div' else 'tag("div", attrs, change(attrs))'
    comparison = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import div, tag
from pyjs.web.ssr import render_html

def change(attrs: dict[str, str]) -> str:
    del attrs["old"]
    attrs["x"] = "late"
    attrs["new"] = "<&"
    gc_collect()
    return "kid"

def main() -> str:
    gc_set_threshold(1)
    attrs = {{"x": "early", "old": "gone"}}
    return render_html({call})
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("child", ['"text"', 'div("child")', '*["one", "two"]', '*children'])
@pytest.mark.parametrize("opaque", [False, True])
def test_child_builders_cannot_bypass_append_override(child, opaque):
    with pytest.raises(LLVMUnsupported, match="DOM append overrides require a concrete application method call"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def append(self, *nodes: str | Element) -> None:
        pass

def fill(item: {"Element" if opaque else "Item"}) -> None:
    children: list[str | Element] = ["text", div()]
    tag(item, {child})

def main() -> str:
    item = Item()
    fill(item)
    return render_html(item)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_attribute_only_builder_does_not_call_append_override(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def append(self, *nodes: str | Element) -> None:
        self.calls += 1

def main() -> str:
    item = Item()
    tag(item, {"x": "value"})
    return render_html(item) + str(item.calls)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expansion", ["parts", "stream(parts)"])
def test_new_builder_snapshots_expansions_and_reads_late_dictionary_values(tmp_path, optimize, expansion):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div
from pyjs.web.ssr import render_html

def stream(parts: list[dict[str, str] | Element | str]) -> Iterator[dict[str, str] | Element | str]:
    for value in parts:
        yield value

def change(parts: list[dict[str, str] | Element | str], attrs: dict[str, str]) -> str:
    parts.clear()
    attrs["x"] = "late" + str(2)
    gc_collect()
    return "tail"

def main() -> str:
    gc_set_threshold(1)
    attrs = {"x": "early"}
    parts: list[dict[str, str] | Element | str] = [attrs, div("nested"), "text" + str(1)]
    return render_html(div(*EXPANSION, change(parts, attrs)))
'''.replace("EXPANSION", expansion), directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
