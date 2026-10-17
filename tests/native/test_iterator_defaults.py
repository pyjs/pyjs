import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import TUPLE_ITERATOR_DEFAULT_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_iterator_defaults_keep_concrete_values_and_gc_roots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def values(present: bool) -> Iterator[object]:
            gc_collect()
            if present:
                yield "item"
            return 7

        def main() -> str:
            gc_set_threshold(1)
            result: list[object] = []
            for present in [False, True]:
                result.append(next(values(present), "fallback"))
                result.append(next(values(present), int(int8(130))))
                result.append(next(values(present), [1, 2]))
                result.append(next(values(present), None))
                gc_collect()
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_is_evaluated_before_resume_and_does_not_hide_errors(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def fallback(events: list[str]) -> list[int]:
            events.append("default")
            gc_collect()
            return [1, 2]

        def values(events: list[str], mode: int) -> Iterator[object]:
            events.append("resume")
            gc_collect()
            if mode == 1:
                raise ValueError("failed")
            if mode == 2:
                yield "item"

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            result: list[object] = []
            for mode in range(3):
                source = values(events, mode)
                try:
                    result.append(next(source, fallback(events)))
                except ValueError as error:
                    gc_collect()
                    events.append(str(error))
            return repr(result) + repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_scalar_union(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
def main() -> str:
    items = iter([1])
    first = next(items, "done")
    second = next(items, "done")
    return repr((first, second))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_optional_union(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
def values() -> Iterator[int | str]:
    yield 7
    yield "value"
def main() -> str:
    gc_set_threshold(1)
    items = values()
    result = [next(items, None), next(items, None), next(items, None)]
    gc_collect()
    return repr(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_represented_union(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs import int8
def values() -> Iterator[int8]:
    yield int8(127)
def main() -> str:
    items = values()
    result = next(items, "missing")
    missing = next(items, "missing")
    if isinstance(result, int):
        return str(result + int8(1)) + repr(missing)
    return result
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_ordinary_int_float(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
def main() -> str:
    items = iter([1])
    return repr((next(items, 1.5), next(items, 1.5)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_none_items(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
def values() -> Iterator[None]:
    gc_collect()
    yield None
def main() -> str:
    gc_set_threshold(1)
    items = values()
    first = next(items, "missing")
    second = next(items, "missing")
    same = next(values(), None)
    gc_collect()
    return repr((first, second, same))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_reference_upcast(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self, label: str):
        self.label = label
    def describe(self) -> str:
        return "base-" + self.label
class Child(Base):
    def describe(self) -> str:
        gc_collect()
        return "child-" + self.label
def values(present: bool) -> Iterator[Child]:
    gc_collect()
    if present:
        yield Child("item")
def main() -> str:
    gc_set_threshold(1)
    fallback = Base("fallback")
    first = next(values(True), fallback)
    second = next(values(False), fallback)
    item = Base("item")
    third = next(iter([item]), Child("unused"))
    gc_collect()
    return repr((first.describe(), second.describe(), second is fallback,
                 third.describe(), third is item))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_callable_default(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Callable, Iterator
from pyjs.native import gc_collect, gc_set_threshold
def first(value: int) -> int:
    gc_collect()
    return value + 1
def second(value: int) -> int:
    gc_collect()
    return value + 2
def values(present: bool) -> Iterator[Callable[[int], int]]:
    gc_collect()
    if present:
        yield first
def main() -> str:
    gc_set_threshold(1)
    one = next(values(True), second)
    two = next(values(False), second)
    gc_collect()
    return repr((one(10), two(10)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_custom_cursor_effects(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Box:
    def __init__(self, label: str):
        self.label = label
    def __repr__(self) -> str:
        return self.label
class Finished(StopIteration):
    pass
class Cursor:
    def __init__(self, events: list[str]):
        self.events = events
        self.count = 0
    def __iter__(self) -> "Cursor":
        self.events.append("unexpected-iter")
        return self
    def __next__(self) -> object:
        self.events.append("next")
        self.count += 1
        gc_collect()
        if self.count == 1:
            return Box("item-" + str(self.count))
        if self.count == 2:
            raise Finished("complete")
        if self.count == 3:
            raise ValueError("retry")
        return "resumed-" + str(self.count)
def fallback(events: list[str], fail: bool) -> list[Box]:
    events.append("default")
    if fail:
        raise ValueError("default failed")
    value = [Box("fallback-" + str(len(events)))]
    gc_collect()
    return value
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    cursor = Cursor(events)
    results: list[str] = []
    previous: object = "unchanged"
    for fail in (True, False, False, False, False):
        try:
            previous = next(cursor, fallback(events, fail))
            gc_collect()
            if isinstance(previous, Box):
                results.append(previous.label)
            else:
                results.append(str(previous))
        except ValueError as error:
            gc_collect()
            results.append(str(error))
            results.append(str(previous))
    return repr(results) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("item, fallback, message", [
    ("int8", '"missing"', r"explicit int\(\) or float\(\)"),
    ("object", "int8(130)", r"explicit int\(\) or float\(\)"),
])
def test_next_does_not_erase_portable_scalar_representation(item, fallback, message):
    yielded = "int8(127)" if item == "int8" else '"item"'
    declaration = f"default: object = {fallback}" if item == "int8" else f"default = {fallback}"
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
from collections.abc import Iterator
from pyjs import int8
def values() -> Iterator[{item}]:
    yield {yielded}
def main() -> str:
    {declaration}
    return repr(next(values(), default))
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_iterator_defaults_preserve_identity_and_representation(tmp_path, optimize):
    contract = TUPLE_ITERATOR_DEFAULT_CONTRACT
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert not result.native.stderr


def test_next_does_not_reinterpret_mutable_container_storage():
    with pytest.raises(LLVMUnsupported, match="different layouts of the same container class"):
        transpile_llvm('''
def main() -> str:
    return repr(next(iter([[True]]), [1]))
''')


@pytest.mark.parametrize("item, fallback", [
    ("int8", "(int16(1),)"),
    ("int8", "(1,)"),
    ("list[int]", "([True],)"),
    ("list[int8]", "([int16(1)],)"),
])
def test_tuple_iterator_defaults_cannot_reinterpret_item_storage(item, fallback):
    with pytest.raises((CompilationError, LLVMUnsupported), match="representation|different layouts"):
        transpile_llvm(f'''from pyjs import int8, int16
def main() -> str:
    rows: list[tuple[{item}, ...]] = []
    return repr(next(iter(rows), {fallback}))
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_next_boxing_failure_preserves_binding_and_cursor_progress(tmp_path, optimize):
    source = transpile_llvm('''
from pyjs.native import gc_collect
from tests.native.allocation_support import arm, remaining
def main() -> int:
    default: object = "default"
    fallback = [1, 2]
    for mode in (0, 1):
        failure = 0
        stages = 1
        while failure <= stages:
            numbers = iter([1000000])
            empty: list[object] = []
            absent = iter(empty)
            saved: object = "saved"
            value = saved
            caught = False
            arm(1000 if failure == 0 else failure)
            try:
                if mode == 0:
                    value = next(numbers, default)
                else:
                    value = next(absent, fallback)
            except MemoryError:
                caught = True
            if failure == 0:
                stages = 1000 - remaining()
            arm(0)
            gc_collect()
            if stages < 1 or caught != (failure != 0):
                return 1
            if caught and value is not saved:
                return 2
            if not caught and str(value) != ("1000000" if mode == 0 else "[1, 2]"):
                return 3
            if mode == 0:
                if next(numbers, default) is not default:
                    return 4
            else:
                if str(next(absent, fallback)) != "[1, 2]":
                    return 5
            failure += 1
    return 0
''')
    # Both boxing branches require the managed heap; do not label this as an
    # arena test merely because a fixture omits an explicit gc_* operation.
    assert "define ptr @pyjs.gc.new()" in source
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_locals_after_control_flow_keep_boxing_widths_and_iterable_adapters(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Iterable
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def check() -> None:
    raise ValueError("test")
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    for _ in range(2):
        try:
            check()
        except ValueError as error:
            events.append(str(error))
    try:
        check()
    except ValueError:
        pass
    scalar: int8 = int8(130)
    rows: Iterable[object] = [1, 2]
    boxed: object = "text"
    try:
        check()
    except ValueError:
        gc_collect()
        events.append(repr(boxed))
        events.append(repr(list(rows)))
        events.append(str(scalar))
    return repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
