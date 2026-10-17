import subprocess

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation, accepted, result", [
    ("filter(None, values)", 1, "value.size"),
    ("filter(bool, values)", 1, "value.size"),
    ("filterfalse(None, values)", 0, "value.size"),
    ("filterfalse(bool, values)", 0, "value.size"),
    ("takewhile(bool, values)", 1, "value.size"),
    ("map(bool, values)", 1, "value"),
])
def test_lazy_truth_length_errors_preserve_bindings_and_allow_resume(
    tmp_path, optimize, operation, accepted, result,
):
    source = '''
        from itertools import filterfalse, takewhile
        from pyjs.native import gc_collect, gc_set_threshold

        class Sized:
            def __init__(self, size: int, events: list[int]):
                self.size = size
                self.events = events

            def __len__(self) -> int:
                self.events.append(self.size)
                gc_collect()
                return self.size

        def main() -> int:
            gc_set_threshold(1)
            events: list[int] = []
            values = [Sized(ACCEPTED, events), Sized(-1, events), Sized(ACCEPTED, events)]
            cursor = OPERATION
            value = next(cursor)
            print(RESULT)
            try:
                value = next(cursor)
            except ValueError:
                gc_collect()
                print("caught", RESULT, events)
            value = next(cursor)
            print("resumed", RESULT, events)

            events.clear()
            try:
                for value in OPERATION:
                    gc_collect()
                    print("loop", RESULT)
                else:
                    print("unexpected loop completion")
            except ValueError:
                print("loop caught", RESULT, events)

            events.clear()
            retained = [7]
            try:
                retained = [7 for value in OPERATION]
            except ValueError:
                gc_collect()
                print("materialization caught", retained, events)
            return 0
    '''
    source = source.replace("OPERATION", operation)
    source = source.replace("ACCEPTED", str(accepted)).replace("RESULT", result)
    execution = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not execution.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_lazy_bool_callbacks_prefer_bool_and_preserve_dropwhile_progress(tmp_path, optimize):
    execution = LLVM().assert_matches_python('''
        from itertools import dropwhile, filterfalse
        from pyjs.native import gc_collect, gc_set_threshold

        class Truth:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __bool__(self) -> bool:
                self.events.append(self.value)
                gc_collect()
                if self.value == -1:
                    raise TypeError("truth failed")
                return self.value != 0

            def __len__(self) -> int:
                raise AssertionError("bool must take precedence")

        def main() -> int:
            gc_set_threshold(1)
            events: list[int] = []
            values = [Truth(1, events), Truth(-1, events), Truth(0, events), Truth(2, events)]
            cursor = dropwhile(bool, values)
            value = Truth(99, events)
            try:
                value = next(cursor)
            except TypeError:
                gc_collect()
                print("caught", value.value, events)
            print(next(cursor).value, next(cursor).value, events)

            events.clear()
            cursor = filterfalse(bool, values)
            try:
                value = next(cursor)
            except TypeError:
                gc_collect()
                print("filter caught", value.value, events)
            print(next(cursor).value, events)

            events.clear()
            mapped = map(bool, values)
            print(next(mapped))
            try:
                next(mapped)
            except TypeError:
                gc_collect()
                print("map caught", events)
            print(next(mapped), next(mapped), events)
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not execution.native.stderr


def test_lazy_truth_length_failure_reports_the_consuming_call(tmp_path):
    source = '''class Sized:
    def __len__(self) -> int:
        return -1

def main() -> int:
    cursor = filter(None, [Sized()])
    next(cursor)
    return 0
'''
    llvm = transpile_llvm(source, filename="iterator_truth.py")
    executable = LLVM().compile(llvm, tmp_path, optimize=0)
    result = subprocess.run([executable], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == (
        'Traceback (native PyJS):\n'
        '  File "iterator_truth.py", line 7, in main\n'
        '  File "iterator_truth.py", line 6, in iterator_step.0\n'
        'ValueError: __len__() should return >= 0\n'
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_aliased_index_and_bool(tmp_path, optimize):
    execution = LLVM().assert_matches_python('''
import itertools as tools
import operator as ops
from builtins import bool as truth
from itertools import filterfalse as reject
from pyjs.native import gc_collect, gc_set_threshold
class Box:
    def __init__(self, value: int, events: list[int]):
        self.value = value
        self.events = events
    def __index__(self) -> int:
        self.events.append(self.value)
        gc_collect()
        if self.value < 0:
            raise ValueError("index")
        return self.value
    def __bool__(self) -> bool:
        self.events.append(self.value + 10)
        gc_collect()
        return self.value != 0
    def __repr__(self) -> str:
        return str(self.value)
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    values = [Box(1, events), Box(0, events), Box(2, events)]
    result: list[str] = []
    result.append(repr(list(tools.takewhile(ops.index, values))))
    result.append(repr(list(tools.dropwhile(ops.index, values))))
    result.append(repr(list(reject(ops.index, values))))
    result.append(repr(list(tools.takewhile(truth, values))))
    result.append(repr(list(tools.dropwhile(truth, values))))
    result.append(repr(list(reject(truth, values))))
    cursor = reject(ops.index, [Box(-1, events), Box(0, events)])
    try:
        next(cursor)
    except ValueError:
        result.append("failed")
    result.append(repr(next(cursor)))
    return repr(result) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not execution.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_effectful_callback_receivers(tmp_path, optimize):
    execution = LLVM().assert_matches_python('''
import itertools as tools
from pyjs.native import gc_collect, gc_set_threshold
class Holder:
    def __init__(self, events: list[str]):
        self.events = events
    def bool(self, value: int) -> bool:
        self.events.append("test" + str(value))
        gc_collect()
        return value > 0
def holder(events: list[str]) -> Holder:
    events.append("receiver")
    gc_collect()
    return Holder(events)
def items(events: list[str]) -> list[int]:
    events.append("items")
    gc_collect()
    return [1, 0, 2]
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    one = tools.takewhile(holder(events).bool, items(events))
    two = tools.dropwhile(holder(events).bool, items(events))
    three = tools.filterfalse(holder(events).bool, items(events))
    before = repr(events)
    result = repr((list(one), list(two), list(three)))
    return before + result + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not execution.native.stderr


@pytest.mark.parametrize("name", ["filterfalse", "takewhile", "dropwhile"])
def test_application_functions_do_not_gain_itertools_builtin_adaptation(name):
    # This is an application function, not the decorated itertools operation.
    # A builtin class cannot silently become a typed lambda just because the
    # consuming function has a familiar name.
    with pytest.raises(LLVMUnsupported, match="class objects"):
        transpile_llvm(f'''
from collections.abc import Callable
def {name}(predicate: Callable[[int], bool], items: list[int]) -> int:
    return 19
def main() -> int:
    return {name}(bool, [1])
''')
