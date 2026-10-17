import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_cast_validation_waits_for_loop_widening(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import cast
class A:
    def __init__(self, value: int): self.value = value
class B:
    def __init__(self, value: int): self.value = value
def choose_class(flag: bool) -> A | B: return A(1) if flag else B(2)
def choose_int(flag: bool) -> int | None: return 5 if flag else None
def choose_object(flag: bool) -> A | None: return A(5) if flag else None
def class_loop() -> int:
    value = choose_class(True)
    total = 0
    if isinstance(value, A):
        for i in range(3):
            current = cast(A | B, value)
            total += current.value
            value = B(i)
    return total
def scalar_loop() -> int:
    value = choose_int(True)
    total = 0
    if value is not None:
        for i in range(3):
            current = cast(int | None, value)
            if current is not None:
                total += current
            value = None
    return total
def object_loop() -> int:
    value = choose_object(True)
    total = 0
    if value is not None:
        while total < 20:
            current = cast(A | None, value)
            total += 100 if current is None else current.value
            value = None
    return total
def main() -> str:
    return str([class_loop(), scalar_loop(), object_loop()])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, entries, read", [
    ("Node", "[Node(1), Node(2)]", "found.value"),
    ("list[int]", "[[1], [2]]", "found[0]"),
    ("str", "['a', 'b']", "len(found)"),
    ("int", "[1, 2]", "found"),
])
@pytest.mark.parametrize("generator", [False, True])
@pytest.mark.parametrize("loop", ["for", "while"])
def test_optional_loop_entry_break_and_exhaustion_keep_none(optimize, annotation, entries, read, generator, loop):
    return_type = "Generator[int, None, None]" if generator else "int"
    suspend = "yield 10" if generator else "pass"
    finish = "yield result" if generator else "return result"
    consume = "list(search(count, stop))" if generator else "search(count, stop)"
    iteration = (f"for found in {entries}[:count]:" if loop == "for" else
                 f"while count > 0:\n                count -= 1\n                found = {entries}[count]")
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Node:
            def __init__(self, value: int):
                self.value = value

        def search(count: int, stop: bool) -> {return_type}:
            found: {annotation} | None = None
            {iteration}
                gc_collect()
                {suspend}
                while True:
                    break
                if stop:
                    break
            else:
                gc_collect()
            gc_collect()
            result = -1
            if found is not None:
                result = {read}
            {finish}

        def main() -> str:
            gc_set_threshold(1)
            result = ''
            for count in [0, 1, 2]:
                for stop in [False, True]:
                    result += str({consume}) + '|'
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("initial, items", [("'s'", "['a', 'b']"), ("0", "[1, 2]")])
def test_object_loop_emits_box_definitions_without_other_object_locals(optimize, initial, items):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect

        def read(count: int) -> str:
            value: object = {initial}
            for value in {items}[:count]:
                gc_collect()
            gc_collect()
            return str(value)

        def main() -> str:
            return read(0) + read(1) + read(2)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_loop_break_merges_the_value_after_finally(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def main() -> str:
            found: list[int] | None = None
            for found in [[1]]:
                try:
                    break
                finally:
                    found = None
                    gc_collect()
            return "none" if found is None else str(found[0])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("position", ["before", "inside", "after"])
def test_loop_capture_uses_the_same_physical_cell_as_its_owner(optimize, position):
    captured = "lambda: int(cast(list[int8], value)[0] + 1)"
    before = captured if position == "before" else "lambda: 0"
    inside = f"read = {captured}" if position == "inside" else "pass"
    after = f"read = {captured}" if position == "after" else "pass"
    result = LLVM().assert_matches_python(f'''
        from typing import Callable, cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def check(count: int) -> int:
            value: object = [int8(127)]
            read: Callable[[], int] = {before}
            for value in [[int8(125)], [int8(126)]][:count]:
                {inside}
                gc_collect()
            {after}
            gc_collect()
            return read()

        def main() -> str:
            gc_set_threshold(1)
            return str(check(0)) + '|' + str(check(1)) + '|' + str(check(2))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
