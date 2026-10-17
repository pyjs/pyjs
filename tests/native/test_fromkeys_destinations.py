"""Fresh mappings choose destination value slots without widening shared aliases."""

import pytest

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


def test_fromkeys_retains_inferred_key_and_value_representations():
    with analyze_source('''
from pyjs import int8
def values():
    return dict.fromkeys([int8(1)], int8(127))
def main() -> int:
    return len(values())
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        key, value = analysis.entry_point.container.search("values").return_representation.arguments
        assert key.numeric.bits == value.numeric.bits == 8
        assert key.numeric.signed and value.numeric.signed


def test_fromkeys_context_is_present_before_native_lowering():
    with analyze_source('''
from pyjs import int8
def main(keys: list[int8]) -> int:
    values: dict[int8 | None, str] = dict.fromkeys(keys, "value")
    return len(values)
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        values = analysis.entry_point.scope.lookup("values")
        assignment = analysis.entry_point.ir.blocks[0].body[0]
        assert analyzed_value_type(assignment.value) is values.cls
        assert assignment.value.representation == values.representation
        members = values.cls.generic_types["K"].types
        representations = values.representation.arguments[0].arguments
        assert {member.name: rep.numeric.bits if rep else None
                for member, rep in zip(members, representations, strict=True)} == {"int": 8, "NoneType": None}
        assert analysis.types == '''def main(keys: list__int) -> int:
    block entry:
        values: dict[int | None, str] = dict__int_str.[dict__int_str]fromkeys(keys, 'value')
        return len(values)'''


@pytest.mark.parametrize("arguments, message", [
    ("*args", "dict.fromkeys does not support expanded arguments"),
    ("*(keys,)", "dict.fromkeys does not support expanded arguments"),
    ("keys, **empty", r"dynamic \*\* argument expansion is not supported"),
])
def test_fromkeys_expanded_arguments_have_an_explicit_boundary(arguments, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm(f'''
def main() -> int:
    keys = [1]
    args = (keys, 2)
    empty: dict[str, int] = {{}}
    return len(dict.fromkeys({arguments}))
''')
    assert caught.value.lineno == 6


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_fresh_fromkeys_destinations_keep_mutable_value_slots(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold

def make(flag: bool) -> str:
    rows: list[dict[int, int | None]] = [dict.fromkeys([1]), dict.fromkeys([2])]
    computed: list[dict[int, int | None]] = [dict.fromkeys([i]) for i in range(2)]
    selected: dict[int, int | None] = dict.fromkeys([3]) if flag else dict.fromkeys([4])
    mapping: dict[str, dict[int, int | None]] = {"entry": dict.fromkeys([5])}
    pair: tuple[dict[int, int | None], int] = (dict.fromkeys([6]), 7)
    gc_collect()
    rows[0][1] = 11
    computed[1][1] = 12
    selected[3 if flag else 4] = 13
    mapping["entry"][5] = 14
    pair[0][6] = 15
    gc_collect()
    return repr((rows, computed, selected, mapping, pair))

def main() -> str:
    gc_set_threshold(1)
    return make(True) + "|" + make(False)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_fromkeys_values_across_destination_boundaries(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold

class Holder:
    def __init__(self):
        self.values: dict[int, int | None] = {}

def make() -> dict[int, int | None]:
    return dict.fromkeys([1, 2])

def fill(values: dict[int, int | None]) -> str:
    gc_collect()
    assert values[1] is None
    values[1] = 7
    return repr(values)

def main() -> str:
    gc_set_threshold(1)
    local: dict[int, int | None] = dict.fromkeys([1, 2])
    mapped: dict[int, float | None] = dict.fromkeys({1: "a", 2: "b"})
    members: dict[int, bool | None] = dict.fromkeys({1, 2}, None)
    holder = Holder()
    holder.values = dict.fromkeys([1, 2])
    mapped[1] = 2.5
    members[2] = True
    gc_collect()
    assert mapped[2] is None and mapped[1] == 2.5
    assert members[1] is None and members[2] is True
    return "|".join([fill(local), fill(make()), fill(holder.values),
                     fill(dict.fromkeys([1, 2]))])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_contextual_fromkeys_keeps_one_shared_default(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs import int8
from pyjs.native import gc_collect

def main() -> str:
    shared = [1]
    values: dict[int, list[int] | None] = dict.fromkeys([1, 2], shared)
    numbers: dict[int, int8 | None] = dict.fromkeys([1, 2], int8(127))
    empty_numbers: dict[int, int8 | None] = dict.fromkeys([1, 2])
    assert empty_numbers[1] is None
    empty_numbers[1] = int8(127)
    copied = dict.fromkeys([int8(1)], int8(127))
    assert copied[int8(1)] + 1 == int8(-128)
    assert next(iter(copied)) + 127 == int8(-128)
    shared.append(2)
    gc_collect()
    assert values[1] is shared and values[2] is shared
    numbers[1] = int8(-128)
    values[2] = None
    return repr((values[1], values[2], numbers[1], numbers[2]))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("expression", ["existing", "forward()"])
def test_existing_fromkeys_results_cannot_widen_mutable_views(expression):
    with pytest.raises(LLVMUnsupported, match="invariant"):
        transpile_llvm(f'''
def forward() -> dict[int, None]:
    return dict.fromkeys([1])
def main() -> int:
    existing = forward()
    widened: dict[int, int | None] = {expression}
    return len(widened)
''')


def test_shared_default_cannot_widen_nested_mutable_storage():
    with pytest.raises(LLVMUnsupported, match="invariant"):
        transpile_llvm('''
def main() -> int:
    shared = [1]
    values: dict[int, list[int | None]] = dict.fromkeys([1], shared)
    return len(values)
''')


@pytest.mark.parametrize("annotation, expression, message", [
    ("dict[int16, None]", "dict.fromkeys([int8(1)])", "incompatible nested representation"),
    ("dict[int, int16]", "dict.fromkeys([1], int8(127))", "different fixed-width numeric types"),
    ("dict[int, int]", "dict.fromkeys([1], int8(127))", "representation"),
    ("dict[int, float]", "dict.fromkeys([1], 1)", "explicit numeric conversion"),
    ("dict[int, int | None]", "dict.fromkeys([1], True)", "explicit conversion"),
    ("dict[int, int | None]", "Factory.fromkeys([1])", "invariant"),
])
def test_fromkeys_does_not_hide_incompatible_storage(annotation, expression, message):
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm(f'''
from pyjs import int8, int16
class Factory:
    @staticmethod
    def fromkeys(keys: list[int]) -> dict[int, None]:
        return dict.fromkeys(keys)
def main() -> int:
    values: {annotation} = {expression}
    return len(values)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_contextual_fromkeys_evaluates_receiver_keys_default_once(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from builtins import dict as Mapping
from pyjs.native import gc_collect

def receiver(events: list[str]) -> dict[int, list[int]]:
    events.append("receiver")
    gc_collect()
    return {}
def keys(events: list[str]) -> list[int]:
    events.append("keys")
    gc_collect()
    return [1, 2, 1]
def default(events: list[str]) -> list[int]:
    events.append("default")
    gc_collect()
    return [3]
def main() -> str:
    events: list[str] = []
    values: dict[int, list[int] | None] = receiver(events).fromkeys(keys(events), default(events))
    assert values[1] is values[2]
    aliased: dict[int, int | str] = Mapping.fromkeys([1], 7)
    erased: dict[int, object] = Mapping.fromkeys([1], [4])
    gc_collect()
    return repr((events, values, aliased, erased))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
