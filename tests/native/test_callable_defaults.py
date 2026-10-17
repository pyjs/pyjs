"""Callable values bind the selected implementation's defaults at invocation."""

import re

import pytest

from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import CALLABLE_DEFAULT_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expression", ["callback(40)", "view(40)"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_signed_defaults_support_full_and_omitted_arity(tmp_path, expression, optimize):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        def read(value: int = -1) -> int:
            return value + 2
        def main() -> str:
            callback = read
            view: Callable[[int], int] = callback
            return str({expression})
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "42"
    assert comparison.native.stderr == ""
    omitted = LLVM().assert_matches_python('''
        def read(value: int = -1) -> int:
            return value + 2
        def main() -> str:
            callback = read
            return str(callback())
    ''', directory=tmp_path / "omitted", optimize=optimize, sanitizers=("address", "undefined"))
    assert omitted.native.stdout == "1"
    assert omitted.native.stderr == ""


def test_unused_nonliteral_default_does_not_reject_full_arity(tmp_path):
    source = '''
        def read(value: int = 2 - 3) -> int:
            return value + 2
        def main() -> str:
            callback = read
            return str(callback(40))
    '''
    result = LLVM().assert_matches_python(source, directory=tmp_path,
                                          sanitizers=("address", "undefined"))
    assert result.native.stdout == "42"
    assert result.native.stderr == ""
    with pytest.raises(LLVMUnsupported, match="must be an immutable constant"):
        transpile_llvm(source.replace("callback(40)", "callback()"))


def test_default_wrapper_trace_contains_only_authored_frames(tmp_path):
    result = LLVM().run_source('''
        from collections.abc import Callable
        def fail(value: int = 1) -> int:
            raise ValueError("callback failed")
        def main() -> str:
            callback: Callable[[int], int] = fail
            return repr(callback(2))
    ''', filename="default_trace.py", directory=tmp_path)
    assert result.returncode < 0
    assert result.stderr == (
        "Traceback (native PyJS):\n"
        '  File "default_trace.py", line 7, in main\n'
        '  File "default_trace.py", line 4, in fail\n'
        "ValueError: callback failed\n"
    )


@pytest.mark.parametrize("call", ["b.read({value}, 3)", "b.read(value={value}, extra=3)",
                                  "b.read({value})", "b.read(*[{value}])",
                                  'b.read(**{{"value": {value}}})'])
@pytest.mark.parametrize("nonuniform", [False, True])
def test_nested_virtual_calls_emit_supplied_arguments_once(call, nonuniform, tmp_path):
    source = "class Base:\n    def read(self, value: int = 0, extra: int = 1) -> int:\n        return value + extra\n"
    for index in range(3):
        default = "" if nonuniform else " = 0"
        source += f"class Child{index}(Base):\n    def read(self, value: int{default}, extra: int = {index + 2}) -> int:\n        return value + extra\n"
    source += "def make(index: int) -> Base:\n"
    for index in range(3):
        source += f"    if index == {index}:\n        return Child{index}()\n"
    source += "    return Base()\ndef mark() -> int:\n    return 2\n"
    value = "mark()"
    for _ in range(4):
        value = call.format(value=value)
    source += f"def main() -> str:\n    b = make(2)\n    return str({value})\n"
    ir = transpile_llvm(source)
    # Whole IR includes large runtime scaffolding. Count this authored leaf's
    # call instruction, not wall time or a hardware-dependent byte threshold.
    assert len(re.findall(r"\bcall i64 @fn.mark\(", ir)) == 1
    comparison = LLVM().assert_matches_python(source, directory=tmp_path,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_binding_keeps_expansion_order_and_default_roots(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def read(self, value: object = 11, extra: object = 12, *, history: list[int] = []) -> str:
                history.append(1)
                gc_collect()
                return str(value) + ":" + str(extra) + ":" + str(len(history))
        class Child(Base):
            def read(self, value: object = 21, extra: object = 22, *, history: list[int] = []) -> str:
                history.append(1)
                gc_collect()
                return str(value) + ":" + str(extra) + ":" + str(len(history))
        def mutate(values: list[object]) -> object:
            values[0] = 3
            gc_collect()
            return 5
        def main() -> str:
            gc_set_threshold(1)
            child: Base = Child()
            values: list[object] = [2]
            omitted = child.read()
            deferred = child.read(*values, extra=mutate(values))
            values[0] = 2
            immediate = child.read(*values, mutate(values))
            again = child.read()
            expanded = child.read(*[])
            return omitted + ";" + deferred + ";" + immediate + ";" + again + ";" + expanded
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "21:22:1;3:5:2;2:5:3;21:22:4;21:22:5"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_default_boxing_failure_unwinds_roots_and_retries(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Base:
            def read(self, value: object = 11, extra: object = 12) -> str:
                gc_collect()
                return str(value) + str(extra)
        class Child(Base):
            def read(self, value: object = 21, extra: object = 22) -> str:
                gc_collect()
                return str(value) + str(extra)
        def main() -> int:
            child: Base = Child()
            for failure in range(1, 3):
                arm(failure)
                failed = False
                try:
                    child.read()
                except MemoryError:
                    failed = True
                arm(0)
                assert failed
                gc_collect()
                assert child.read() == "2122"
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_callable_default_contract(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(CALLABLE_DEFAULT_CONTRACT.source,
        directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 0
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_bound_callable_uses_the_selected_overrides_defaults(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __init__(self, offset: int):
                self.offset = offset
            def read(self, value: int, extra: int = 30, *, history: list[int] = []) -> int:
                history.append(value)
                return self.offset + value + extra + len(history)
        class Child(Base):
            def read(self, value: int, extra: int = 40, *, history: list[int] = []) -> int:
                history.append(value)
                gc_collect()
                return self.offset + value + extra + len(history)
        def selected(value: Base) -> Callable[[int], int]:
            return value.read
        def direct(value: Base) -> int:
            return value.read(2)
        def main() -> str:
            gc_set_threshold(1)
            child: Base = Child(100)
            callback = child.read
            projected = selected(child)
            gc_collect()
            return str((callback(1), direct(child), projected(3), selected(Base(10))(4), callback(5, 20)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(142, 144, 146, 45, 129)"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_shorter_callable_views_bind_defaults_without_losing_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def read(value: int, extra: int = 10) -> int:
            gc_collect()
            return value + extra
        def consume(callback: Callable[[int], int]) -> int:
            return callback(2)
        def selected() -> Callable[[int], int]:
            return read
        def main() -> str:
            gc_set_threshold(1)
            callback = read
            short: Callable[[int], int] = callback
            full: Callable[[int, int], int] = callback
            gc_collect()
            return str((short(1), full(2, 20), consume(callback), selected()(3), short is callback))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(11, 22, 12, 13, True)"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_callable_omits_positional_and_keyword_defaults(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def read(value: int, extra: int | None = 10, *, history: list[int] = []) -> int:
            history.append(value)
            gc_collect()
            if value < 0:
                raise ValueError("negative")
            return value + (100 if extra is None else extra) + len(history)
        def main() -> str:
            gc_set_threshold(1)
            callback = read
            first = callback(1)
            second = callback(2, None)
            try:
                callback(-1)
            except ValueError:
                pass
            return str(first) + ":" + str(second) + ":" + str(callback(3))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "12:104:17"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_callable_views_preserve_numeric_widths_boxing_and_void(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold
        def show(value: object, extra: object = "default") -> str:
            gc_collect()
            return str(value) + ":" + str(extra)
        def wide(value: int64, extra: int64 = 2) -> int64:
            return value + extra
        def small(value: int8, extra: int8 = 2) -> int8:
            return value + extra
        def record(values: list[int], value: int = 10) -> None:
            gc_collect()
            values.append(value)
        def main() -> str:
            gc_set_threshold(1)
            callback = show
            short: Callable[[int], str] = callback
            full: Callable[[int, str], str] = callback
            result = [callback(1), callback(2, None), short(3), full(4, "given")]
            large = wide
            numeric: Callable[[int64], int64] = large
            result.append(str(numeric(int64(9007199254740993))))
            result.append(str(large(int64(9007199254740993), int64(4))))
            tiny = small
            result.append(str(tiny(int8(127))))
            result.append(str(tiny(int8(127), int8(3))))
            values: list[int] = []
            sink = record
            sink(values)
            sink(values, 20)
            fixed: Callable[[list[int]], None] = sink
            fixed(values)
            result.append(str(values))
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("scalar", ["int", "int8"])
def test_default_adapter_allocation_failure_preserves_previous_binding(tmp_path, optimize, scalar):
    source = transpile_llvm(f'''
        from collections.abc import Callable
        from pyjs import int8
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        def first(value: {scalar}) -> {scalar}:
            return value
        def second(value: {scalar}, extra: {scalar} = 20) -> {scalar}:
            gc_collect()
            return value + extra
        def main() -> int:
            callback: Callable[[{scalar}], {scalar}] = first
            failed = False
            arm(1)
            try:
                callback = second
            except MemoryError:
                failed = True
            arm(0)
            gc_collect()
            if not failed or callback is not first or int(callback({scalar}(2))) != 2:
                return 1
            callback = second
            gc_collect()
            return 0 if int(callback({scalar}(2))) == 22 and callback is second else 2
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_conditional_optional_callbacks_preserve_result_adapters(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def broad(value: int, extra: int = 20) -> object:
            gc_collect()
            return value + extra
        def narrow(value: int, extra: int = 10) -> int:
            gc_collect()
            return value + extra
        def run(flag: bool) -> str:
            callback = broad if flag else narrow
            return str(callback(1)) + ":" + str(callback(2, 30))
        def main() -> str:
            gc_set_threshold(1)
            return run(True) + ":" + run(False)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "21:32:11:32"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_consumers_apply_defaults(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from functools import reduce
        from itertools import accumulate, groupby
        from pyjs.native import gc_collect, gc_set_threshold
        def key(value: int, direction: int = 1) -> int:
            gc_collect()
            return -value * direction
        def keep(value: int, threshold: int = 2) -> bool:
            return value >= threshold
        def add(left: int, right: int, extra: int = 10) -> int:
            gc_collect()
            return left + right + extra
        def main() -> str:
            gc_set_threshold(1)
            values = [3, 1, 2]
            mapped = list(map(key, values))
            filtered = list(filter(keep, values))
            ordered = sorted(values, key=key)
            values.sort(key=key)
            groups: list[int] = []
            for name, group in groupby([1, 1, 2], key=key):
                groups.append(name)
                groups.append(sum(group))
            return str((mapped, filtered, ordered, values, min(values, key=key),
                        max(values, key=key), reduce(add, values, 0),
                        list(accumulate(values, add)), groups))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_dispatch_roots_receivers_and_keeps_super_lexical(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def read(self, value: int = 10) -> int:
                return value
        class Child(Base):
            def read(self, value: int = 20) -> int:
                gc_collect()
                return super().read() + value
        def argument(owners: list[Base], trace: list[int]) -> int:
            owners.clear()
            gc_collect()
            trace.append(1)
            return 3
        def direct(owners: list[Base], trace: list[int]) -> int:
            return owners[0].read(argument(owners, trace))
        def extracted(owners: list[Base], trace: list[int]) -> int:
            callback = owners[0].read
            return callback(argument(owners, trace))
        def main() -> str:
            gc_set_threshold(1)
            trace: list[int] = []
            return str((direct([Child()], trace), extracted([Child()], trace), trace))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(13, 13, [1, 1])"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_keyword_only_defaults_keep_fixed_positional_callback_abi(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def read(value: int, *, history: list[int] = []) -> int:
            history.append(value)
            gc_collect()
            return sum(history)
        def factory() -> Callable[[int], int]:
            return read
        def main() -> str:
            gc_set_threshold(1)
            callback = read
            view = factory()
            return str((callback(1), view(2), callback(3), view is callback))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(1, 3, 6, True)"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_zero_argument_view_of_optional_function(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect
        def read(value: int = 10, extra: int = 20) -> int:
            gc_collect()
            return value + extra
        def main() -> str:
            callback = read
            zero: Callable[[], int] = callback
            return str((callback(), callback(1), callback(1, 2), zero(), zero is callback))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(30, 21, 3, 30, True)"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_conditional_arity_intersection_and_default_only_keyword_function(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect
        def optional(value: int, extra: int = 10) -> int:
            gc_collect()
            return value + extra
        def required(value: int, extra: int) -> int:
            return value - extra
        def keyword(*, value: int = 42) -> int:
            return value
        def run(flag: bool) -> int:
            callback = optional if flag else required
            return callback(8, 3)
        def main() -> str:
            callback: Callable[[], int] = keyword
            return str((run(True), run(False), callback()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(11, 5, 42)"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_and_nested_default_views(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def read(value: int, extra: int = 10) -> int:
            gc_collect()
            return value + extra
        def optional(flag: bool) -> Callable[[int], int] | None:
            return read if flag else None
        def factory():
            return read
        def main() -> str:
            gc_set_threshold(1)
            callback = optional(True)
            if callback is None:
                return "missing"
            nested: Callable[[], Callable[[int], int]] = factory
            callbacks: list[Callable[[int], int]] = [read, nested()]
            gc_collect()
            return str((callback(1), nested()(2), callbacks[0](3),
                        callbacks[1](4), optional(False) is None))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(11, 12, 13, 14, True)"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("result", ["int", "str"])
def test_union_bound_methods_intersect_optional_arities(tmp_path, optimize, result):
    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Optional:
            def read(self, value: int, extra: int = 10) -> int:
                gc_collect()
                return value + extra
        class Required:
            def read(self, value: int, extra: int) -> {result}:
                gc_collect()
                return {result}(value - extra)
        def run(value: Optional | Required) -> int | {result}:
            callback = value.read
            gc_collect()
            return callback(8, 3)
        def main() -> str:
            gc_set_threshold(1)
            return str((run(Optional()), run(Required())))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == ("(11, 5)" if result == "int" else "(11, '5')")
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_initialization_failure_is_retryable_through_a_callback(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        def read(values: list[int] = [10]) -> int:
            values.append(2)
            gc_collect()
            return sum(values)
        def main() -> int:
            callback = read
            failed = False
            arm(1)
            try:
                callback()
            except MemoryError:
                failed = True
            arm(0)
            gc_collect()
            if not failed or callback() != 12:
                return 1
            return 0 if read() == 14 and callback() == 16 else 2
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_format_property_and_void_defaults_use_the_runtime_owner(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            @property
            def value(self, *, offset: int8 = 10) -> int8:
                return offset
            def __format__(self, spec: str, *, prefix: str = "base") -> str:
                gc_collect()
                return prefix + spec
            def record(self, values: list[int], *, count: int = 1) -> None:
                values.append(count)
        class Child(Base):
            @property
            def value(self, *, offset: int8 = 20) -> int8:
                gc_collect()
                return offset
            def __format__(self, spec: str, *, prefix: str = "child") -> str:
                gc_collect()
                return prefix + spec
            def record(self, values: list[int], *, count: int = 2) -> None:
                gc_collect()
                values.append(count)
        def describe(value: Base) -> str:
            events: list[int] = []
            value.record(events)
            return str((value.value, format(value, "!"), events))
        def main() -> str:
            gc_set_threshold(1)
            return describe(Base()) + describe(Child())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "(10, 'base!', [1])(20, 'child!', [2])"
    assert comparison.native.stderr == ""
