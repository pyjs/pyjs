"""Nominal cursor recovery must not reinterpret the iterator handle as an object."""

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_cursor_nominal_checks_recover_each_specialization(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
class Cursor[T]:
    def __init__(self, value: T):
        self.value = value
    def __iter__(self) -> Cursor[T]:
        return self
    def __next__(self) -> T:
        gc_collect()
        return self.value
class Other[T]:
    def __init__(self, value: T):
        self.value = value
def integer(value: Iterator[int] | None) -> str:
    gc_collect()
    return repr((isinstance(value, Cursor), isinstance(value, Other)))
def text(value: Iterator[str]) -> bool:
    gc_collect()
    return isinstance(value, Cursor)
def opaque(value: Iterator[object]) -> bool:
    gc_collect()
    return isinstance(value, Cursor)
def generated() -> Iterator[int]:
    yield 9
def main() -> str:
    gc_set_threshold(1)
    number = Cursor[int](7)
    word = Cursor[str]('hello')
    view: Iterator[int] = number
    adapted: Iterator[object] = word
    result = integer(view) + integer(None) + integer(iter([1])) + integer(generated())
    return result + repr((isinstance(number, Cursor), text(word), opaque(adapted),
                          view is number, adapted is word, next(view), next(adapted)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("item", ["Box", "object"])
def test_cursor_nominal_checks_and_narrowed_access(tmp_path, optimize, item):
    source = '''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
class Box:
    def __init__(self, value: int):
        self.value = value
class Cursor:
    def __init__(self):
        self.position = 0
    def __iter__(self) -> Cursor:
        return self
    def __next__(self) -> Box:
        self.position += 1
        gc_collect()
        return Box(self.position)
class Derived(Cursor):
    def __next__(self) -> Box:
        self.position += 10
        gc_collect()
        return Box(self.position)
class Other:
    def __init__(self):
        self.position = 100
    def __iter__(self) -> Other:
        return self
    def __next__(self) -> Box:
        self.position += 1
        return Box(self.position)
class Holder:
    def __init__(self, value: Iterator[ITEM] | None):
        self.value = value
def adapt(value: Cursor) -> Iterator[ITEM]:
    return value
def generated() -> Iterator[Box]:
    yield Box(8)
def inspect(value: Iterator[ITEM] | None) -> str:
    if isinstance(value, Derived):
        value.position += 1
        return "derived:" + str(value.position)
    if isinstance(value, Cursor):
        value.position += 2
        return "base:" + str(value.position)
    if isinstance(value, Other):
        return "other:" + str(value.position)
    return "none" if value is None else "builtin"
def main() -> str:
    gc_set_threshold(1)
    original = Cursor()
    derived = Derived()
    first = adapt(original)
    second = adapt(derived)
    next(first)
    next(second)
    holder = Holder(second)
    result = inspect(first) + ";" + inspect(second)
    if isinstance(holder.value, Derived):
        gc_collect()
        holder.value.position += 3
        result += ";field:" + str(holder.value.position)
    other: Iterator[ITEM] = Other()
    result += ";" + inspect(other) + ";" + inspect(iter([Box(1)])) + ";" + inspect(None)
    result += ";" + inspect(generated())
    # The recovered object and every view still share one identity/state.
    result += ";" + repr((first is original, second is derived, holder.value is derived))
    return result + ";" + str(original.position) + ";" + str(derived.position)
'''.replace("ITEM", item)
    comparison = LLVM().assert_matches_python(source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("replacement", ["iter([1, 2])", "None"])
def test_cursor_narrowing_rechecks_rebound_field(tmp_path, optimize, replacement):
    # CPython raises AttributeError here; native's existing stale-flow contract
    # is a checked TypeError. Both are safe failures, not object-layout reads.
    comparison = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs.native import gc_collect
class Cursor:
    def __init__(self):
        self.position = 7
    def __iter__(self) -> Cursor:
        return self
    def __next__(self) -> int:
        return self.position
class Holder:
    def __init__(self, value: Iterator[int] | None):
        self.value = value
def replace(holder: Holder) -> None:
    holder.value = REPLACEMENT
    gc_collect()
def main() -> str:
    holder = Holder(Cursor())
    if isinstance(holder.value, Cursor):
        replace(holder)
        try:
            return str(holder.value.position)
        except (TypeError, AttributeError):
            return "safe"
    return "missed"
'''.replace("REPLACEMENT", replacement), directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
