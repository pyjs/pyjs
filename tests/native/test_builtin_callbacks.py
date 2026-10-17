"""Builtin conversion callbacks reuse typed lambda/call lowering."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_callbacks_cross_iterator_boundaries_and_gc(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def keep_int(values: Iterator[int]) -> Iterator[int]:
            gc_collect()
            return values

        def keep_str(values: Iterator[str]) -> Iterator[str]:
            gc_collect()
            return values

        def keep_bool(values: Iterator[bool]) -> Iterator[bool]:
            gc_collect()
            return values

        def keep_float(values: Iterator[float]) -> Iterator[float]:
            gc_collect()
            return values

        def main() -> str:
            gc_set_threshold(1, byte_limit=128)
            labels = keep_str(map(str, [1, True, -2]))
            selected = keep_int(filter(bool, [0, 2, -1, 0]))
            flags = keep_bool(map(bool, [0, 2, -1, 0]))
            integers = keep_int(map(int, [False, True, True]))
            floats = keep_float(map(float, [0, 2, -3]))
            truth_floats = keep_float(map(float, [False, True]))
            gc_collect()
            return (
                "|".join(labels) + ":" + ",".join(map(str, selected))
                + ":" + ",".join(map(str, flags)) + ":" + ",".join(map(str, integers))
                + ":" + ",".join(map(str, floats)) + ":" + ",".join(map(str, truth_floats))
            )
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_callbacks_are_lazy_resume_and_retain_conversion_protocols(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Value:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __str__(self) -> str:
                gc_collect()
                self.events.append(self.value)
                if self.value == 2:
                    raise ValueError("skip")
                return "v" + str(self.value)

            def __bool__(self) -> bool:
                gc_collect()
                return self.value != 0

        def main() -> str:
            gc_set_threshold(1, byte_limit=128)
            values = map(int, [1.9, math.nan, -2.9, math.inf, 4.2])
            parts = [str(next(values))]
            try:
                next(values)
            except ValueError:
                parts.append("nan")
            parts.append(str(next(values)))
            try:
                next(values)
            except OverflowError:
                parts.append("infinity")
            parts.extend(map(str, values))
            events: list[int] = []
            labels = map(str, [Value(1, events), Value(2, events), Value(3, events)])
            assert not events
            parts.append(next(labels))
            try:
                next(labels)
            except ValueError as error:
                parts.append(str(error))
            parts.extend(labels)
            assert events == [1, 2, 3]
            assert len(list(filter(bool, [Value(0, events), Value(1, events)]))) == 1
            assert list(map(int, [int8(127), int8(-128)])) == [127, -128]
            assert list(map(float, [float32(1.25), float32(-0.5)])) == [1.25, -0.5]
            return ":".join(parts)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_resolution_uses_identity_not_spelling(optimize):
    result = LLVM().assert_matches_python('''
        from builtins import str as stringify
        from collections.abc import Callable

        def transform(value: int) -> int:
            return value + 3

        def select(value: int) -> bool:
            return value > 2

        def apply(str: Callable[[int], int], bool: Callable[[int], bool]) -> int:
            assert list(map(stringify, [5, 6])) == ["5", "6"]
            return sum(map(str, [1, 2])) + sum(filter(bool, [1, 3, 2, 4]))

        def shadow(map: Callable[[int], int]) -> int:
            return map(3)

        def main() -> str:
            assert apply(transform, select) == 16
            assert shadow(transform) == 6
            assert list(map(stringify, [1, 2])) == ["1", "2"]
            return ":".join(map(stringify, [3, 4]))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("call", [
    'map(int, ["10", "11"], [2, 2])',
    'map(str, [b"a", b"b"], ["utf-8", "utf-8"])',
])
def test_multi_iterable_conversions_diagnose_the_source_not_a_synthetic_lambda(call):
    # These are valid Python constructor overloads, but outside the native
    # one-iterable adapter contract. Diagnose before creating a hidden lambda.
    with pytest.raises(CompilationError, match="Native builtin conversion callbacks require exactly one iterable") as caught:
        transpile_llvm(f"def main() -> str:\n    return str(list({call}))\n", filename="callbacks.py")
    assert caught.value.filename == "callbacks.py"
    assert caught.value.lineno == 2
