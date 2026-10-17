import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("annotation,expression", [
    ("Iterable[int]", "sum(forward([20, 22]))"),
    ("object", "forward(42)"),
    ("Callable[[int], int]", "forward(lambda value: value + 2)(40)"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_forwarding_inline_prepares_declared_arguments(tmp_path, annotation, expression, optimize):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Callable, Iterable
        from pyjs import llvm
        from pyjs.native import gc_collect, gc_set_threshold
        @llvm.inline("{{value}}")
        def forward(value: {annotation}) -> {annotation}:
            return value
        def main() -> str:
            gc_set_threshold(1)
            result = {expression}
            gc_collect()
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "42"
    assert result.native.stderr == ""


@pytest.mark.parametrize("argument", ["panel", "value=panel"])
@pytest.mark.parametrize("template", ["{value}", "select i1 true, ptr {value}, ptr {value}"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_inline_projects_application_wrapper_to_dom(tmp_path, argument, template, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs import llvm
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, div, tag
        from pyjs.web.ssr import render_html
        @llvm.inline({template!r})
        def forward(value: Element) -> Element:
            return value
        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
                tag(self, div("hello <&>"))
        def main() -> str:
            panel = Panel()
            element = forward({argument})
            element.setAttribute("title", "native")
            return render_html(element)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inline_instruction_roots_the_materialized_adapter(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Iterable
        from pyjs import llvm
        from pyjs.native import gc_collect
        @llvm.inline("call i64 @probe(ptr %arg.__heap, ptr {value})")
        def inspect(value: Iterable[int]) -> int:
            return sum(value)
        def main() -> int:
            gc_collect()
            return inspect([20, 22])
    ''') + '''
        define i64 @probe(ptr %heap, ptr %value) {
          call void @pyjs.gc.collect(ptr %heap)
          %found = call ptr @pyjs.gc.find(ptr %heap, ptr %value)
          %live = icmp ne ptr %found, null
          %result = select i1 %live, i64 42, i64 1
          ret i64 %result
        }
    '''
    # The declaration is the only reached Iterable boundary. Its acquisition
    # helper must be linkable even though the instruction does not iterate it.
    executable = LLVM().compile(source, tmp_path, optimize=optimize,
                                sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
    assert result.returncode == 42
    assert result.stderr == ""


@pytest.mark.parametrize("annotation,value", [("object", "42"), ("Iterable[int]", "[20, 22]")])
@pytest.mark.parametrize("optimize", [0, 2])
def test_instruction_inline_returns_declared_storage(tmp_path, annotation, value, optimize):
    consume = "sum(result)" if annotation == "Iterable[int]" else "result"
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterable
        from pyjs import llvm
        from pyjs.native import gc_collect, gc_set_threshold
        @llvm.inline("select i1 true, ptr {{value}}, ptr {{value}}")
        def forward(value: {annotation}) -> {annotation}:
            return value
        def main() -> str:
            gc_set_threshold(1)
            result = forward({value})
            gc_collect()
            return str({consume})
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "42"
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_forwarded_numeric_operands_recover_semantic_width(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import float32, float64, int8, int64, llvm
        @llvm.inline("{value}")
        def integer(value: int8) -> int64:
            return int64(value)
        @llvm.inline("{value}")
        def floating(value: float32) -> float64:
            return float64(value)
        def main() -> str:
            return str(integer(int8(-128))) + ':' + str(floating(float32(1.25)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
