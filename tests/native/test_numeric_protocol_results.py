"""Protocol results are validated as values, never recursively converted."""

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_indices_keep_subclass_dispatch_after_explicit_scalar_conversion(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from operator import index
from pyjs import int8, int64
from pyjs.native import gc_collect, gc_set_threshold
class Position:
    def __init__(self, events: list[int], value: int):
        self.events, self.value = events, value
    def __index__(self) -> int:
        self.events.append(self.value)
        gc_collect()
        return self.value
class Last(Position):
    def __index__(self) -> int:
        gc_collect()
        self.events.append(99)
        return -1
def inspect(value: object, values: list[int]) -> int:
    values[value] = 7
    return index(value)
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    values = [0, 0, 0]
    inputs: list[object] = [True, False, Position(events, 1), Last(events, 2)]
    inputs.append(int(int8(257)))
    inputs.append(int(int64(2)))
    result: list[int] = []
    for value in inputs:
        result.append(inspect(value, values))
        gc_collect()
    return repr(result) + repr(values) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_index_errors_preserve_mutation_and_suspended_handlers(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs.native import gc_collect, gc_set_threshold
class Broken:
    def __index__(self) -> int:
        gc_collect()
        raise ValueError("broken index")
class Invalid:
    def __index__(self) -> str:
        return "not an integer"
class IntOnly:
    def __int__(self) -> int:
        return 1
def source(values: list[int]) -> Generator[int, int, None]:
    try:
        values[(yield 1)] = 9
        yield values[0]
    except TypeError:
        yield -1
def main() -> str:
    gc_set_threshold(1)
    result: list[int] = []
    values = [0]
    empty: list[int] = []
    inputs: list[object] = [None, 1.5, "0", empty, Invalid(), IntOnly(), Broken()]
    for value in inputs:
        try:
            values[value] = 8
            result.append(100)
        except TypeError:
            result.append(1)
        except ValueError:
            result.append(2)
        assert values == [0]
        gc_collect()
    first = source(values)
    result.extend([next(first), first.send(0)])
    first.close()
    second = source(values)
    result.extend([next(second), next(second)])
    second.close()
    return repr(result) + repr(values)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_uncaught_erased_index_failure_preserves_native_source_trace(tmp_path, optimize):
    comparison = LLVM().compare_with_python('''from operator import index

def read(value: object) -> int:
    return index(value)

def main() -> int:
    return read(None)
''', filename="index_failure.py", directory=tmp_path, optimize=optimize)
    assert comparison.python.returncode != 0
    assert comparison.native.returncode != 0
    assert comparison.native.stderr == (
        'Traceback (native PyJS):\n'
        '  File "index_failure.py", line 7, in main\n'
        '  File "index_failure.py", line 4, in read\n'
        'TypeError: object cannot be interpreted as an integer\n'
    )


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation, method, number, scalar", [
    ("index", "__index__", "7", "int"),
    ("int", "__int__", "7", "int"),
    ("float", "__float__", "2.5", "float"),
])
@pytest.mark.parametrize("result_type, invalid", [
    ("SCALAR | None", "None"),
    ("SCALAR | str", "'bad'"),
    ("SCALAR | OTHER", "WRONG"),
    ("object", "self"),
    ("object", "WRONG"),
    ("str", "'bad'"),
])
def test_numeric_callbacks_check_results_after_effects_without_recursion(
    tmp_path, optimize, operation, method, number, scalar, result_type, invalid,
):
    annotation = result_type.replace("SCALAR", scalar).replace("OTHER", "int" if scalar == "float" else "float")
    invalid = invalid.replace("WRONG", "1" if scalar == "float" else "1.5")
    success = "'also invalid'" if annotation == "str" else number
    fallback = "" if method == "__index__" else '''
    def __index__(self) -> int:
        self.events.append("unexpected fallback")
        return 99
'''
    comparison = LLVM().assert_matches_python(f'''
from operator import index
from pyjs.native import gc_collect, gc_set_threshold
class Value:
    def __init__(self, mode: int, events: list[str]):
        self.mode, self.events = mode, events
    def {method}(self) -> {annotation}:
        self.events.append("called" + str(self.mode))
        gc_collect()
        if self.mode == 0:
            return {success}
        if self.mode == 1:
            return {invalid}
        raise ValueError("callback failure")
{fallback}
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    results: list[str] = []
    for mode in range(3):
        try:
            results.append(str({operation}(Value(mode, events))))
        except TypeError:
            results.append("invalid")
        except ValueError:
            results.append("raised")
        gc_collect()
    return repr((results, events))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_index_results_keep_last_owner_and_reject_recursive_conversion(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from operator import index
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
class Position:
    def __init__(self, owners: list[object], saved: list[object]):
        self.owners, self.saved = owners, saved
        self.value = 3
    def __index__(self) -> object:
        self.owners.clear()
        self.saved.append(self)
        gc_collect()
        return int(int8(self.value))
class Recursive:
    def __index__(self) -> object:
        return self
class Optional:
    def __init__(self, valid: bool):
        self.valid = valid
    def __index__(self) -> int | None:
        return 4 if self.valid else None
class Mixed:
    def __init__(self, valid: bool):
        self.valid = valid
    def __index__(self) -> int | str:
        return 5 if self.valid else "bad"
def consume(owners: list[object]) -> int:
    return index(owners[0])
def main() -> str:
    gc_set_threshold(1)
    owners: list[object] = []
    saved: list[object] = []
    owners.append(Position(owners, saved))
    result = [consume(owners)]
    gc_collect()
    result.append(index(saved[0]))
    gc_collect()
    result.append(len(saved))
    alternatives: list[object] = [Recursive(), Optional(True), Optional(False), Mixed(True), Mixed(False), True]
    for value in alternatives:
        try:
            result.append(index(value))
        except TypeError:
            result.append(-1)
    return repr(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_index_result_kinds_normalize_before_ordinary_numeric_use(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from enum import IntEnum
from operator import index
from pyjs import int8
class Count(IntEnum):
    TWO = 2
class Boolean:
    def __index__(self) -> bool:
        return True
class EnumIndex:
    def __index__(self) -> Count:
        return Count.TWO
class Portable:
    def __index__(self) -> int8:
        return int8(-128)
class ErasedBoolean:
    def __index__(self) -> object:
        return True
class ConvertedEnum:
    def __index__(self) -> object:
        return int(Count.TWO)
class Fallback:
    def __init__(self, valid: bool):
        self.valid = valid
    def __index__(self) -> int | None:
        return 3 if self.valid else None
def main() -> str:
    result = repr((index(Boolean()), index(EnumIndex()), index(Portable()) - 1,
                   index(ErasedBoolean()), index(ConvertedEnum()),
                   int(Fallback(True)), float(Fallback(True))))
    try:
        float(Fallback(False))
    except TypeError:
        result += "invalid"
    return result
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_checked_index_results_are_shared_by_integer_consumers(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from itertools import islice, repeat
from math import gcd
from pyjs.native import gc_collect, gc_set_threshold
class Index:
    def __init__(self, valid: bool, events: list[int]):
        self.valid, self.events = valid, events
    def __index__(self) -> int | str:
        self.events.append(1)
        gc_collect()
        return 2 if self.valid else "bad"
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    results: list[str] = []
    for valid in [True, False]:
        index = Index(valid, events)
        for mode in range(10):
            values = [1, 2, 3, 4]
            try:
                if mode == 0:
                    results.append(str(values[index]))
                elif mode == 1:
                    values[index] = 9
                elif mode == 2:
                    del values[index]
                elif mode == 3:
                    results.append(str(values.pop(index)))
                elif mode == 4:
                    results.append(repr(values[index:]))
                elif mode == 5:
                    results.append(repr(list(range(index))))
                elif mode == 6:
                    results.append(str(gcd(index, 6)))
                elif mode == 7:
                    results.append(repr(list(islice(values, index))))
                elif mode == 8:
                    results.append(repr(list(repeat(5, times=index))))
                else:
                    results.append("a,b,c,d".split(",", maxsplit=index)[-1])
            except TypeError:
                results.append("invalid")
            except ValueError:
                # islice deliberately remaps invalid stop-index TypeError.
                results.append("invalid count")
            results.append(repr(values))
    return repr((results, events))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
