import ast
import re
import subprocess
from types import SimpleNamespace

import pytest

from pyjs.analysis.ir import IteratorCreate, IteratorNext, Jump, Return, Suspend
from pyjs.native.iterator_ops import dead_roots
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.gc_support import observe_collections


def block(name, body, exceptional=None):
    return SimpleNamespace(name=name, body=body, exception_target=exceptional)


def test_cursor_cleanup_preserves_failed_definitions_and_suspend_edges():
    blocks = [
        block("replace", [IteratorCreate("cursor", ast.Constant(None)), Jump("next")], "handler"),
        block("handler", [Jump("next")]),
        block("next", [IteratorNext("cursor", ast.Name(id="value"), "yield", "done")]),
        block("yield", [Suspend(ast.Constant(1), "next")]),
        block("done", [Jump("after")]),
        block("after", [Return(ast.Constant(0))]),
    ]
    assert dead_roots(blocks) == {
        "replace": (), "handler": (), "next": (), "yield": (),
        "done": ("cursor",), "after": (),
    }


def test_unknown_cursor_control_flow_disables_release():
    blocks = [block("entry", [IteratorCreate("cursor", ast.Constant(None)), ast.Pass()])]
    assert dead_roots(blocks) == {}


def test_sequential_loop_cleanup_has_linear_emitted_size():
    counts = []
    for count in (8, 16, 32):
        source = "from pyjs.native import gc_collect\ndef main() -> int:\n    gc_collect()\n    total = 0\n"
        for index in range(count):
            source += f"    for value{index} in [1, 2]:\n        total += value{index}\n"
        source += "    return total\n"
        emitted = transpile_llvm(source)
        # Isolate the authored body, not unrelated runtime/helper definitions.
        body = re.search(r"^define [^\n]*@fn\.pyjs_main\([^\n]*\).*?^}", emitted, re.M | re.S)
        assert body is not None
        counts.append(body.group().count("store ptr null"))
    assert counts[2] - counts[1] == 2 * (counts[1] - counts[0]), counts


def test_handler_cleanup_does_not_multiply_unrelated_expression_roots():
    counts = {}
    for statements, handlers in ((2, 2), (2, 4), (4, 2), (4, 4)):
        source = '''from pyjs.native import gc_collect
class Box:
    def __init__(self, value: str):
        self.value = value
def main() -> str:
    gc_collect()
    result = ""
'''
        source += '    result += Box("plain").value\n' * statements
        source += '''    try:
        result += [Box("guarded")][0].value
    except IndexError:
        result += "caught"
''' * handlers
        source += "    return result\n"
        emitted = transpile_llvm(source)
        # The large shared runtime obscures this function-local size contract.
        body = re.search(r"^define [^\n]*@fn\.pyjs_main\([^\n]*\).*?^}", emitted, re.M | re.S)
        assert body is not None
        counts[statements, handlers] = body.group().count("store ptr null")
    # Extra unprotected statements must cost the same with either handler count.
    assert counts[4, 4] - counts[2, 4] == counts[4, 2] - counts[2, 2], counts


@pytest.mark.parametrize("optimize", [0, 2])
def test_loop_roots_are_released_on_break_and_exception_but_survive_continue(tmp_path, optimize):
    source = transpile_llvm('''
from pyjs.native import gc_collect
from tests.native.gc_support import live
def items() -> list[int]:
    return [0, 1, 2]
def main() -> int:
    gc_collect()
    baseline = live()
    outer_baseline = 0
    for outer in items():
        gc_collect()
        if outer == 0:
            outer_baseline = live()
            if outer_baseline <= baseline:
                return 7
        elif live() != outer_baseline:
            return 1
        for inner in [0, 1, 2]:
            if inner == 0:
                continue
            break
        else:
            return 2
        gc_collect()
        if live() != outer_baseline:
            return 3
        try:
            for inner in [0, 1, 2]:
                raise ValueError()
        except ValueError:
            gc_collect()
            if live() != outer_baseline:
                return 4
        try:
            raise ValueError()
        except ValueError:
            gc_collect()
            continue
    gc_collect()
    if live() != baseline:
        return 5
    for index in [0, 1, 2]:
        try:
            break
        finally:
            gc_collect()
            if index == 0:
                continue
    gc_collect()
    if index != 1 or live() != baseline:
        return 6
    return 0
''')
    # Measure actual managed allocations at authored collection points. The
    # producer-returned source (not just its new managed cursor) escapes into
    # this frame and must remain live when an inner loop or handler exits.
    source = observe_collections(source)
    executable = LLVM().compile(source, tmp_path, optimize=optimize)
    result = subprocess.run([executable], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert not result.stderr
