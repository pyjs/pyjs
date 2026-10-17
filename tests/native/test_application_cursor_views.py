"""Application cursors reuse the lazy typed iterator view contract."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_cursor_protocol_calls_do_not_create_interface_dependencies(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
class Box:
    def __init__(self, value: int):
        self.value = value
class Cursor:
    def __iter__(self) -> Cursor:
        return self
    def __next__(self) -> Box:
        return Box(7)
def main() -> int:
    return Cursor().__iter__().__next__().value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_cursor_views_in_locals_fields_and_callback_results(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable, Iterator
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
class Holder:
    def __init__(self, view: Iterator[object]):
        self.view = view
def acquire() -> Cursor:
    return Cursor()
def factory(callback: Callable[[], Iterator[object]]) -> Iterator[object]:
    gc_collect()
    return callback()
def main() -> str:
    gc_set_threshold(1)
    original = Cursor()
    local: Iterator[object] = original
    holder = Holder(original)
    callback_view = factory(acquire)
    first = next(local)
    second = next(holder.view)
    third = next(callback_view)
    # Direct protocol calls do not by themselves require Iterator[Box] views.
    direct = original.__iter__().__next__()
    gc_collect()
    assert isinstance(first, Box) and isinstance(second, Box) and isinstance(third, Box)
    return repr((first.value, second.value, third.value, direct.value,
                 local is holder.view, local is original))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_cursor_views_share_identity_state_and_completion(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
class Cursor:
    def __init__(self, events: list[str]):
        self.position = 0
        self.events = events
    def __iter__(self) -> Cursor:
        self.events.append("iter")
        gc_collect()
        return self
    def __next__(self) -> int:
        self.position += 1
        self.events.append("next" + str(self.position))
        gc_collect()
        if self.position == 2:
            raise ValueError("retry")
        if self.position >= 4:
            raise StopIteration(["done"])
        return self.position
def widen(value: Cursor | None) -> Iterator[object] | None:
    return value
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    original = Cursor(events)
    view = widen(original)
    assert view is not None
    assert widen(None) is None
    assert view is original
    assert events == []
    first = next(view)
    try:
        next(original)
    except ValueError:
        events.append("caught")
    else:
        return "missing error"
    assert iter(view) is view
    second = next(view)
    result: object = None
    try:
        next(view)
    except StopIteration as error:
        result = error.value
    gc_collect()
    assert next(view, None) is None
    return repr((first, second, result, events))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_cursor_views_keep_represented_reference_items_and_reacquisition(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Iterator
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
class Cursor:
    def __init__(self, values: list[list[int8]], fresh: bool):
        self.values = values
        self.position = 0
        self.fresh = fresh
    def __iter__(self) -> Cursor:
        gc_collect()
        return Cursor(self.values, False) if self.fresh else self
    def __next__(self) -> list[int8]:
        if self.position >= len(self.values):
            raise StopIteration("done")
        value = self.values[self.position]
        self.position += 1
        gc_collect()
        return value
def widen(value: Cursor) -> Iterator[object]:
    return value
def main() -> str:
    gc_set_threshold(1)
    values = [[int8(127)], [int8(-128)]]
    original = Cursor(values, True)
    view = widen(original)
    first = cast(list[int8], next(view))
    assert first is values[0]
    first[0] += int8(1)
    fresh = iter(view)
    assert fresh is not view
    item = cast(list[int8], next(fresh))
    assert item is first
    values.clear()
    gc_collect()
    item[0] -= int8(1)
    assert next(view, None) is None
    return repr((first, item, original.position))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("item,target,value", [
    ("int8", "object", "int8(127)"),
    ("int8", "int16", "int8(127)"),
    ("list[int8]", "list[int]", "[int8(127)]"),
])
def test_application_cursor_views_do_not_erase_scalar_or_mutable_item_layouts(item, target, value):
    with pytest.raises(CompilationError, match="Custom iterator items use an incompatible representation"):
        transpile_llvm(f'''
from collections.abc import Iterator
from pyjs import int8, int16
class Cursor:
    def __iter__(self) -> Cursor:
        return self
    def __next__(self) -> {item}:
        return {value}
def widen(value: Cursor) -> Iterator[{target}]:
    return value
def main() -> str:
    return str(next(widen(Cursor())))
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_cursor_item_views_retain_implicit_virtual_protocols(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Iterable, Iterator
from pyjs.native import gc_collect, gc_set_threshold
class Bag:
    def __iter__(self) -> Iterator[int]:
        yield 1
class Child(Bag):
    def __iter__(self) -> Iterator[int]:
        gc_collect()
        yield 2
        yield 3
class Cursor:
    def __init__(self, bag: Bag):
        self.bag = bag
    def __iter__(self) -> Cursor:
        return self
    def __next__(self) -> Bag:
        gc_collect()
        return self.bag
def widen(value: Cursor) -> Iterator[Iterable[int]]:
    return value
def consume(value: Bag) -> list[int]:
    cursor = widen(Cursor(value))
    item = next(cursor)
    gc_collect()
    return list(item)
def main() -> str:
    gc_set_threshold(1)
    # No direct call to Bag/Child.__iter__ may accidentally retain these bodies.
    return repr((consume(Bag()), consume(Child())))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_cursor_view_allocation_failures_keep_source_state(tmp_path, optimize):
    source = transpile_llvm('''
from collections.abc import Iterator
from pyjs.native import gc_collect
from tests.native.allocation_support import arm, remaining
class Cursor:
    def __init__(self):
        self.position = 0
        self.fail = False
    def __iter__(self) -> Cursor:
        return self
    def __next__(self) -> int:
        self.position += 1
        if self.fail:
            self.fail = False
            arm(1)
        return self.position
def widen(value: Cursor) -> Iterator[object]:
    return value
def main() -> int:
    original = Cursor()
    arm(1000)
    probe = widen(original)
    stages = 1000 - remaining()
    arm(0)
    assert stages > 0 and original.position == 0
    for failure in range(1, stages + 1):
        arm(failure)
        try:
            widen(original)
        except MemoryError:
            arm(0)
        else:
            arm(0)
            return 1
        gc_collect()
        assert original.position == 0
    retry = widen(original)
    assert next(retry) == 1
    assert next(probe) == 2
    original.fail = True
    try:
        next(retry)
    except MemoryError:
        arm(0)
    else:
        arm(0)
        return 2
    gc_collect()
    # Boxing follows advancement. An allocation error must not rewind the
    # user cursor, consume another item, or leave the adapter unusable.
    assert original.position == 3
    assert next(retry) == 4
    assert next(original) == 5
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
