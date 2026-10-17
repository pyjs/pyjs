"""Implicit item mutation differs from explicit instance attribute lookup."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_item_syntax_selects_class_methods_and_preserves_operand_order(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from operator import setitem, delitem
        from pyjs.native import gc_collect, gc_set_threshold
        class Items:
            def __init__(self, events: list[str]):
                self.events = events
                self.__setitem__: Callable[[int, int], int] = self.fake_set
                self.__delitem__: Callable[[int], int] = self.fake_del
            def __setitem__(self, key: int, value: int) -> int:
                self.events.append("class-set:" + str(value))
                gc_collect()
                return 1
            def __delitem__(self, key: int) -> int:
                self.events.append("class-del")
                gc_collect()
                return 2
            def fake_set(self, key: int, value: int) -> int:
                self.events.append("field-set")
                return 3
            def fake_del(self, key: int) -> int:
                self.events.append("field-del")
                return 4
            def inside(self) -> None:
                self[0] = 7
                del self[0]
        class Disabled(Items):
            __setitem__ = None
            __delitem__ = None
        class Restored(Disabled):
            def __setitem__(self, key: int, value: int) -> int:
                self.events.append("restored")
                return 5
            def __delitem__(self, key: int) -> int:
                self.events.append("restored-del")
                return 6
        def receiver(items: list[Items], events: list[str]) -> Items:
            events.append("receiver")
            return items.pop()
        def argument(events: list[str], label: str, fail: bool) -> int:
            events.append(label)
            gc_collect()
            if fail: raise ValueError(label)
            return 9
        def change(value: Items, events: list[str]) -> None:
            try: value[argument(events, "key", False)] = argument(events, "rhs", False)
            except TypeError: events.append("set-error")
            try: del value[argument(events, "delete-key", False)]
            except TypeError: events.append("del-error")
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            value = Items(events)
            value.inside()
            setitem(value, 0, 8)
            delitem(value, 0)
            explicit = (value.__setitem__(0, 9), value.__delitem__(0))
            change(Disabled(events), events)
            change(Restored(events), events)
            owners: list[Items] = [Items(events)]
            receiver(owners, events)[argument(events, "key", False)] = argument(events, "rhs", False)
            owners.append(value)
            try: receiver(owners, events)[argument(events, "key", False)] = argument(events, "rhs", True)
            except ValueError: events.append("rhs-error")
            try: receiver(owners, events)[argument(events, "key", True)] = argument(events, "rhs", False)
            except ValueError: events.append("key-error")
            return repr((events, explicit, len(owners)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_item_protocol_arguments_suspend_in_assignment_order(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable, Generator
        from pyjs.native import gc_collect, gc_set_threshold
        class Items:
            def __init__(self):
                self.values: list[int] = []
                self.__setitem__: Callable[[int, int], None] = self.fake
            def __setitem__(self, key: int, value: int) -> None:
                gc_collect()
                self.values.append(key + value)
            def __delitem__(self, key: int) -> None:
                gc_collect()
                self.values.append(-key)
            def fake(self, key: int, value: int) -> None:
                self.values.append(-999)
        def changes(target: Items) -> Generator[int, int, None]:
            target[(yield 2)] = (yield 1)
            del target[(yield 3)]
        def main() -> str:
            gc_set_threshold(1)
            target = Items()
            cursor = changes(target)
            stages = [next(cursor)]
            gc_collect()
            stages.append(cursor.send(40))
            gc_collect()
            stages.append(cursor.send(2))
            try: cursor.send(5)
            except StopIteration: stages.append(4)
            return repr((stages, target.values))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("operation", [
    "values[0:2] = [9]", "values[key] = [9]",
    "values.__setitem__(key, [9])",
    "setitem(values, key, [9])", "list(map(setitem, [values], [key], [[9]]))",
])
def test_static_array_slice_mutation_spellings_keep_fixed_shape(operation):
    with pytest.raises(CompilationError, match="Static arrays do not support slice assignment"):
        transpile_llvm(f'''from pyjs import StaticArray
from operator import setitem
def main() -> int:
    values = StaticArray[int, 3]([1, 2, 3])
    key = slice(0, 2)
    {operation}
    return len(values)
''', filename="static_slice.py")


def test_static_array_explicit_keyword_mutation_keeps_collection_call_boundary():
    with pytest.raises(LLVMUnsupported, match="LLVM collection methods require positional arguments"):
        transpile_llvm('''from pyjs import StaticArray
def main() -> int:
    values = StaticArray[int, 3]([1, 2, 3])
    values.__setitem__(index=slice(0, 2), value=[9])
    return len(values)
''')


@pytest.mark.parametrize("operation, name", [
    ("value[0] = 1", "__setitem__"), ("del value[0]", "__delitem__"),
])
def test_implicit_item_syntax_requires_class_protocol(operation, name):
    with pytest.raises(CompilationError, match=f"class-level instance or static {name}") as caught:
        transpile_llvm(f'''from collections.abc import Callable
def setter(key: int, value: int) -> None: pass
def deleter(key: int) -> None: pass
class Items:
    def __init__(self):
        self.__setitem__: Callable[[int, int], None] = setter
        self.__delitem__: Callable[[int], None] = deleter
def main() -> None:
    value = Items()
    {operation}
''', filename="implicit_item.py")
    assert caught.value.lineno == 10
