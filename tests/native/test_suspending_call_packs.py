"""Call staging across yield: snapshots, error order, and retained operands.

Yield expressions include None because next() resumes with None, independently
of the declared send type. Explicit received() checks keep historical staging
scenarios valid without depending on the old implicit argument conversions.
"""

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_suspended_star_calls_snapshot_at_each_argument_boundary(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs.native import gc_collect, gc_set_threshold
def items(values: list[int], events: list[int]):
    for value in values:
        events.append(value)
        gc_collect()
        yield value
def received(value: int | None) -> int:
    if value is None:
        raise TypeError("send an integer")
    return value
def combine(*values: int, last: int) -> int:
    gc_collect()
    return sum(values) + last
def fixed(first: int, second: int, *, last: int) -> int:
    return first + second + last
def source(values: list[int], events: list[int]) -> Generator[int, int, None]:
    yield combine(*items(values, events), last=received((yield 1)))
    yield combine(100, *items(values, events), last=received((yield 2)))
    yield combine(*items(values, events), received((yield 3)), *items(values, events), last=1)
    yield fixed(*values, last=received((yield 4)))
    yield fixed(*tuple(values), last=received((yield 5)))
def main() -> str:
    gc_set_threshold(1)
    values = [10, 20]
    events: list[int] = []
    iterator = source(values, events)
    result: list[str] = []
    for index in range(5):
        result.append(str(next(iterator)))
        result.append(repr(events))
        values[0] += 1
        gc_collect()
        result.append(str(iterator.send(7)))
        result.append(repr(events))
    iterator.close()
    return repr(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_suspended_keyword_groups_snapshot_and_keep_duplicate_error_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs.native import gc_collect, gc_set_threshold
def items(events: list[str]):
    events.append("consume")
    yield "item"
def received(value: str | None) -> str:
    if value is None:
        raise TypeError("send text")
    return value
def collect(*values: str, **options: str) -> str:
    gc_collect()
    return repr(values) + repr(options)
def mark(events: list[str], value: str) -> str:
    events.append(value)
    return value
def source(options: dict[str, str], events: list[str]) -> Generator[str, str, None]:
    yield collect(*items(events), **options, later=received((yield "first")))
    try:
        yield collect(*items(events), **options, **options, later=received((yield "never")))
    except TypeError:
        yield "duplicate"
    try:
        yield collect(**options, name=mark(events, "named"), other=received((yield "group")))
    except TypeError:
        yield "group duplicate"
    yield collect("first", *items(events), **options, last=received((yield "last")))
def main() -> str:
    gc_set_threshold(1)
    options = {"name": "old"}
    events: list[str] = []
    iterator = source(options, events)
    result = [next(iterator), repr(events)]
    options["name"] = "changed"
    options["new"] = "value"
    gc_collect()
    result.append(iterator.send("sent"))
    result.append(repr(events))
    result.append(next(iterator))
    result.append(repr(events))
    result.append(next(iterator))
    result.append(repr(events))
    result.append(iterator.send("group sent"))
    result.append(next(iterator))
    result.append(repr(events))
    options.clear()
    gc_collect()
    result.append(iterator.send("last sent"))
    iterator.close()
    return repr(result) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_suspended_packs_preserve_represented_and_erased_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def received(value: int8 | None) -> int8:
    if value is None:
        raise TypeError("send int8")
    return value
def combine(*values: int8, last: int8) -> int8:
    gc_collect()
    result = last
    for value in values:
        result += value
    return result
def mixed(first: str, second: int, *, last: int8) -> str:
    return first + str(second) + str(last)
def narrow(**values: int8) -> str:
    gc_collect()
    return repr(values)
def wide(**values: object) -> str:
    gc_collect()
    return repr(values)
def source(values: list[int8], options: dict[str, int8], objects: dict[str, object]) -> Generator[str, int8, None]:
    yield str(combine(int8(1), *values, last=received((yield "first"))))
    yield mixed(*("text", 42), last=received((yield "second")))
    yield narrow(**options, next=received((yield "narrow")))
    yield wide(**objects, next=int(received((yield "wide"))))
def main() -> str:
    gc_set_threshold(1)
    values = [int8(127), int8(2)]
    options = {"first": int8(127)}
    objects: dict[str, object] = {"first": int(int8(127)), "nested": ["retained"]}
    iterator = source(values, options, objects)
    result: list[str] = []
    for index in range(4):
        result.append(next(iterator))
        values[0] = int8(0)
        options["first"] = int8(-1)
        objects.clear()
        gc_collect()
        result.append(iterator.send(int8(index + 1)))
    iterator.close()
    return repr(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansion_failure_and_injected_shutdown_skip_later_operands(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs.native import gc_collect
def received(value: int | None) -> int:
    if value is None:
        raise TypeError("send an integer")
    return value
def broken(events: list[str]):
    events.append("item")
    yield 1
    raise ValueError("broken")
def collect(value: int, *values: int, last: int = 0) -> int:
    return value + sum(values) + last
def source(events: list[str]) -> Generator[int, int, None]:
    conflict = {"value": 2}
    duplicate = {"last": 2}
    try:
        yield collect(1, *broken(events), last=received((yield 99)))
    except ValueError:
        yield 1
    try:
        yield collect(*broken(events), last=received((yield 2)))
    except ValueError:
        yield 3
    try:
        yield collect(1, **conflict, last=received((yield 4)))
    except TypeError:
        yield 5
    try:
        yield collect(1, **duplicate, last=received((yield 6)))
    finally:
        events.append("cleanup")
def main() -> str:
    result: list[int] = []
    events: list[str] = []
    for throw in [False, True]:
        iterator = source(events)
        result.append(next(iterator))
        result.append(next(iterator))
        result.append(iterator.send(0))
        result.append(next(iterator))
        result.append(iterator.send(0))
        result.append(next(iterator))
        gc_collect()
        if throw:
            try:
                iterator.throw(ValueError("stop"))
            except ValueError:
                events.append("thrown")
        else:
            iterator.close()
        gc_collect()
    return repr(result) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_suspended_pack_allocation_failure_can_retry_without_entering_callee(tmp_path, optimize):
    source = transpile_llvm('''
from collections.abc import Generator
from pyjs.native import gc_collect
from tests.native.allocation_support import arm, remaining
class Counter:
    def __init__(self):
        self.entered = 0
def received(value: int | None) -> int:
    if value is None:
        raise TypeError("send an integer")
    return value
def collect(counter: Counter, /, *values: int, **options: int) -> int:
    counter.entered += 1
    return len(values) + len(options)
def source(counter: Counter, values: list[int], options: dict[str, int]) -> Generator[int, int, None]:
    yield collect(counter, 100, *values, **options, last=received((yield 1)))
def main() -> int:
    counter = Counter()
    values = list(range(20))
    options = {str(index): index for index in range(20)}
    for phase in range(2):
        stages = 1
        failure = 0
        while failure <= stages:
            counter.entered = 0
            iterator = source(counter, values, options)
            if phase == 1:
                next(iterator)
            caught = False
            result = -1
            arm(1000 if failure == 0 else failure)
            try:
                result = next(iterator) if phase == 0 else iterator.send(2)
            except MemoryError:
                caught = True
            if failure == 0:
                stages = 1000 - remaining()
            arm(0)
            gc_collect()
            if stages < 2 or caught != (failure != 0):
                return 1
            if caught and (counter.entered or result != -1):
                return 2
            if not caught and result != (1 if phase == 0 else 42):
                return 3
            iterator.close()
            if len(values) != 20 or values[19] != 19 or len(options) != 20 or options["19"] != 19:
                return 4
            counter.entered = 0
            retry = source(counter, values, options)
            if next(retry) != 1 or retry.send(2) != 42 or counter.entered != 1:
                return 5
            retry.close()
            gc_collect()
            failure += 1
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_suspended_collection_expansions_capture_members_and_representations(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def source(values: list[int8], mapping: dict[str, int8]) -> Generator[str, int8, None]:
    yield repr([*values, (yield "list"), *values])
    yield repr({**mapping, "value": (yield "dict"), **mapping})
def main() -> str:
    gc_set_threshold(1)
    values = [int8(127)]
    mapping = {"first": int8(1), "value": int8(2)}
    iterator = source(values, mapping)
    result = [next(iterator)]
    values[0] = int8(-128)
    gc_collect()
    result.append(iterator.send(int8(3)))
    result.append(next(iterator))
    mapping.clear()
    mapping["last"] = int8(127)
    gc_collect()
    result.append(iterator.send(int8(4)))
    iterator.close()
    return repr(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansion_sources_delegate_before_becoming_call_arguments(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
def numbers():
    yield "numbers"
    gc_collect()
    return [1, 2]
def mapping():
    yield "mapping"
    gc_collect()
    return {"value": 4}
def collect(*values: int, **options: int) -> str:
    gc_collect()
    return repr(values) + repr(options)
def source():
    yield repr([*(yield from numbers()), 3])
    yield repr({**(yield from mapping()), "last": 5})
    yield collect(0, *(yield from numbers()), **(yield from mapping()), last=6)
def main() -> str:
    return repr(list(source()))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
