"""Function-local state, value boundaries and conservative GC poll elision."""

import re

import pytest

from pyjs.analysis.ir import build_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import FunctionEmitter, LLVMEmitter, ModuleState
from pyjs.tooling.llvm import LLVM


def test_function_emitters_share_discovery_but_not_local_state():
    module = ModuleState("main", "executable", False)
    left, right = FunctionEmitter(module), FunctionEmitter(module)
    left.slots["value"] = "%slot"
    left.value_semantics[("ptr", "%v1")] = "caller"
    left.expression_roots[1] = "%root"
    left.exception_target = "caller.cleanup"
    assert left.emit_value("add i64 1, 2") == "%v1"
    assert right.emit_value("sub i64 4, 3") == "%v1"
    assert right.slots == right.value_semantics == right.expression_roots == {}
    assert right.exception_target is None
    assert left.lines == ["%v1 = add i64 1, 2"]
    assert right.lines == ["%v1 = sub i64 4, 3"]
    assert left.string_constant("shared") == right.string_constant("shared")
    assert len(module.string_constants) == 1


def test_function_emission_is_independent_of_previous_function_state():
    with analyze_source('''
from collections.abc import Iterator
from pyjs.native import gc_collect
def rows(value: int) -> Iterator[int]:
    yield value
    gc_collect()
    yield value + 1
def render(value: int) -> str:
    try:
        return str(list(rows(value)))
    finally:
        gc_collect()
def main() -> str:
    return render(4)
''', entry_point="main", wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        emitter = LLVMEmitter("main")
        program = build_program_ir(analysis.entry_point)
        emitter.emit(program)
        functions = [function for function in program.functions if function.name in {"main", "render", "rows"}]
        assert len(functions) == 3
        forward = {function: FunctionEmitter(emitter.module).function(function) for function in functions}
        reverse = {function: FunctionEmitter(emitter.module).function(function) for function in reversed(functions)}
        assert forward == reverse


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_layouts_cross_virtual_packed_and_nested_callback_boundaries(tmp_path, optimize):
    # Exercise the stored values, not private layout-cache entries. The same
    # metadata must survive independently bound arguments and nested returns.
    result = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs import int8, uint8, float32
from pyjs.native import gc_collect, gc_set_threshold
class Reader:
    def read(self, value: uint8) -> tuple[uint8, float32]:
        return value, float32(0.5)
class Derived(Reader):
    def read(self, value: uint8) -> tuple[uint8, float32]:
        gc_collect()
        if value == uint8(0):
            raise ValueError('zero')
        return value, float32(1.25)
def read(reader: Reader, value: uint8) -> tuple[uint8, float32]:
    return reader.read(value)
def packed(*values: uint8, **extras: float32) -> str:
    gc_collect()
    return repr(values) + repr(extras)
def produce(value: uint8) -> list[tuple[uint8, float32]]:
    values = [(value, float32(1.25))]
    gc_collect()
    return values
def ordinary(value: int) -> list[list[int]]:
    gc_collect()
    return [[value]]
def convert(signed: int8, unsigned: uint8, wide: int) -> uint8:
    # The result's uint8 representation must not narrow the int argument.
    assert int(signed) == -1 and int(unsigned) == 255 and wide == 511
    return uint8(wide)
def main() -> str:
    gc_set_threshold(1)
    reader = Derived()
    callback: Callable[[uint8], tuple[uint8, float32]] = reader.read
    output = [repr(read(reader, uint8(255))), repr(callback(uint8(258)))]
    try:
        read(reader, uint8(256))
    except ValueError as error:
        output.append(str(error))
    output.append(repr(read(reader, uint8(259))))
    output.append(packed(uint8(255), uint8(258), x=float32(1.25)))
    values = [uint8(255), uint8(257)]
    extras = {'y': float32(2.5)}
    output.append(packed(*values, **extras))
    mapping: dict[uint8, float32] = {uint8(255): float32(1.25), uint8(257): float32(2.5)}
    mapping[uint8(258)] = float32(3.75)
    callbacks: list[Callable[[uint8], list[tuple[uint8, float32]]]] = [produce]
    nested = {'saved': callbacks[0](uint8(260))}
    nested['saved'].append(callback(uint8(255)))
    nested['saved'].append((uint8(258), float32(2.5)))
    adapted: list[Callable[[int], object]] = [ordinary]
    boxed = adapted[0](42)
    output.append(str(convert(int8(255), uint8(255), 511)))
    gc_collect()
    return repr(output) + repr(mapping) + repr(nested) + repr(boxed)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_arguments_survive_collection_in_later_arguments(tmp_path, optimize):
    # Callee-side collection alone cannot exercise the caller's temporary
    # roots: later arguments must collect while earlier packs are being bound.
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def churn() -> int:
    junk = [str(i) * 8 for i in range(200)]
    gc_collect()
    return len(junk)
def build(seed: int) -> list[str]:
    return [str(seed) + 'x' * 16, str(seed + 1) + 'y' * 16]
def target(first: list[str], *rest: str, count: int, **extras: list[str]) -> str:
    gc_collect()
    return repr(first) + repr(rest) + str(count) + repr(extras)
def main() -> str:
    gc_set_threshold(1)
    output = ''
    for seed in range(3):
        output += target(build(seed), *build(seed + 10), count=churn(),
                         **{'k': build(seed + 20)}, z=build(churn()))
    return output
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("instruction", [
    "call void @callback()",
    "%result = call ptr @pyjs.gc.alloc(ptr %heap, i64 8)",
    "%result = tail call i64 @recursive(i64 1)",
    "%result = call i64 %callback(i64 1)",
    "invoke void @callback() to label %ok unwind label %failed",
    'callbr void asm sideeffect "", "!i"() to label %ok [label %failed]',
    "%result = call i64 @llvm.unknown.i64(i64 1)",
    "call void @pyjs.gc.frame.push(ptr %heap, ptr %frame, ptr %roots, i64 1)\ncall void @callback()",
])
def test_unknown_lowered_calls_keep_leaf_polling(instruction):
    lines = ["define void @candidate() {", "entry:",
             "  call void @pyjs.gc.maybe.collect(ptr %heap)", f"  {instruction}", "  ret void", "}"]
    assert FunctionEmitter.omit_leaf_gc_polls(lines) == lines


@pytest.mark.parametrize("optimize", [0, 2])
def test_leaf_polling_is_not_inferred_from_scalar_signatures(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs import llvm
from pyjs.native import gc_collect, gc_set_threshold
@llvm.inline("call void @llvm.trap()")
def trap() -> None:
    raise RuntimeError('unreachable')
def checked(value: int) -> int:
    if value < 0:
        trap()
    return value
def leaf(value: int) -> int:
    total = 0
    while value > 0:
        total += value
        value -= 1
    return total
def allocating(value: int) -> int:
    values = [value, value + 1]
    return values[0] + values[1]
def collecting(value: int) -> int:
    gc_collect()
    return value + 1
def indirect(callback: Callable[[int], int], value: int) -> int:
    return callback(value)
def recursive(value: int) -> int:
    if value == 0:
        return 0
    return value + recursive(value - 1)
def main() -> str:
    gc_set_threshold(1)
    retained = ['live ' + str(42)]
    value = leaf(10) + allocating(3) + indirect(collecting, 9) + recursive(3) + checked(0)
    gc_collect()
    return retained[0] + ':' + str(value)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
    assert result.native.stdout == "live 42:78"
    # Match whole application bodies, not similarly named runtime helpers.
    bodies = dict(re.findall(r"^define [^\n]*@fn\.(\w+)\([^\n]*\) \{\n(.*?)^\}",
                             result.native.llvm_ir, re.M | re.S))
    assert {"leaf", "allocating", "collecting", "indirect", "recursive", "checked", "pyjs_main"} <= bodies.keys()
    assert "@pyjs.gc.maybe.collect" not in bodies["leaf"]
    assert "%slot.__expression_" not in bodies["leaf"]
    assert "@pyjs.gc.frame.push" in bodies["leaf"]
    assert "@pyjs.gc.frame.pop" in bodies["leaf"]
    for name in ("allocating", "collecting", "indirect", "recursive", "checked", "pyjs_main"):
        assert "@pyjs.gc.maybe.collect" in bodies[name], name
