"""Read-only set relations compare values without retyping either storage."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import SCALAR_SET_RELATIONS_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_scalar_set_relations(tmp_path, optimize):
    result = LLVM().assert_matches_python(SCALAR_SET_RELATIONS_CONTRACT.source,
        directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, SCALAR_SET_RELATIONS_CONTRACT.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("kind", ["set", "frozenset"])
@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operator, reflected, inverse", [
    ("<", "__gt__", ">"), ("<=", "__ge__", ">="),
    (">", "__lt__", "<"), (">=", "__le__", "<="),
])
def test_set_ordering_retains_reflected_application_methods(tmp_path, optimize, kind, operator, reflected, inverse):
    # Compile each operator separately: direct calls or sibling operators in
    # the same program could mask a missing reflected-name reachability edge.
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
class Bound:
    def __init__(self, count: int, events: list[str]):
        self.count = count
        self.events = events
    def {reflected}(self, other: {kind}[int]) -> bool:
        self.events.append('{reflected}')
        gc_collect()
        if self.count < 0:
            raise ValueError('comparison')
        return self.count {inverse} len(other)
def members(events: list[str]) -> {kind}[int]:
    events.append('members')
    return {kind}([1, 2])
def bound(events: list[str]) -> Bound:
    events.append('bound')
    return Bound(3, events)
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    answers = [members(events) {operator} bound(events)]
    try:
        members(events) {operator} Bound(-1, events)
    except ValueError as error:
        events.append(str(error))
    return repr(answers) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("left_type,left,right_type,right", [
    ("int | None", "[None, 1]", "float", "[1.0]"),
    ("bool", "[True]", "int", "[1]"),
    ("int", "[9007199254740993]", "float", "[9007199254740992.0]"),
    ("int", "[9007199254740992]", "float", "[9007199254740992.0]"),
    ("float", "[float('inf'), float('nan')]", "int", "[0]"),
    ("float", "[-0.0]", "bool", "[False]"),
    ("str", "['é']", "bytes", "[b'\\xc3\\xa9']"),
    ("int | str", "[1, 'x']", "float | str", "[1.0, 'x']"),
    ("None", "[None]", "int", "[0]"),
    ("str", "[]", "int | None", "[]"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_relations_keep_distinct_domains(tmp_path, optimize, left_type, left, right_type, right):
    # Empty constructor-argument inference is a separate write-boundary task.
    # Parameterized empty sets here exercise only read-only comparison.
    left_constructor = "set()" if left == "[]" else f"set({left})"
    right_constructor = "set()" if right == "[]" else f"set({right})"
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect
def main() -> str:
    left: set[{left_type}] = {left_constructor}
    right: set[{right_type}] = {right_constructor}
    flags = [left == right, left != right, left < right, left <= right,
             left > right, left >= right, right < left, right <= left]
    frozen = frozenset(left)
    other = frozenset(right)
    gc_collect()
    flags.extend([frozen == other, frozen <= other, frozen >= right, right <= frozen])
    return repr((flags, len(left), len(right), len(frozen), len(other)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_parameter_only_set_relations_link_without_float_construction(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
def compare(left: set[int] | None, right: set[float] | None) -> bool:
    if left is None or right is None:
        return False
    return left <= right
def main() -> int:
    return int(compare(None, None))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("operation", ["==", "<=", ">="])
def test_set_relations_do_not_mix_portable_widths(operation):
    with pytest.raises((CompilationError, LLVMUnsupported), match="fixed-width|representation"):
        transpile_llvm(f'''
from pyjs import int8, int16
def main() -> bool:
    return {{int8(1)}} {operation} {{int16(1)}}
''')


@pytest.mark.parametrize("other", ["'text'", "[1]", "1"])
@pytest.mark.parametrize("expression", ["values < other", "values.__lt__(other)"])
def test_set_ordering_does_not_read_nonset_storage(other, expression):
    with pytest.raises(LLVMUnsupported, match="set comparison requires set or frozenset"):
        transpile_llvm(f'''
def main() -> bool:
    values = {{1}}
    other = {other}
    return {expression}
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_distinct_set_relation_does_not_allocate_a_converted_copy(tmp_path, optimize):
    source = '''
from pyjs.native import gc_collect
from tests.native.allocation_support import arm, remaining
def main() -> int:
    left: set[int | None] = {None, 1}
    right = {1.0}
    gc_collect()
    arm(1)
    matched = left > right and right <= left and left != right
    untouched = remaining() == 1
    arm(0)
    return 0 if matched and untouched else 1
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)
