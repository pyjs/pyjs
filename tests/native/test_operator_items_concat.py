import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_mutation_uses_class_protocols_not_callable_instance_fields(optimize):
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
                self.events.append("class-set")
                gc_collect()
                return 11
            def __delitem__(self, key: int) -> int:
                self.events.append("class-del")
                gc_collect()
                return 12
            def fake_set(self, key: int, value: int) -> int:
                self.events.append("field-set")
                return 21
            def fake_del(self, key: int) -> int:
                self.events.append("field-del")
                return 22
        class Disabled(Items):
            __setitem__ = None
            __delitem__ = None
        class Static:
            @staticmethod
            def __setitem__(key: int, value: int) -> int: return key + value
            @staticmethod
            def __delitem__(key: int) -> int: return key
        def argument(events: list[str], label: str) -> int:
            events.append(label)
            gc_collect()
            return 1
        def disabled(value: Items, events: list[str]) -> None:
            try: setitem(value, argument(events, "key"), argument(events, "value"))
            except TypeError: events.append("set-error")
            try: delitem(value, argument(events, "key"))
            except TypeError: events.append("del-error")
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            value = Items(events)
            first = setitem(value, 0, 5)
            second = delitem(value, 0)
            explicit = (value.__setitem__(0, 5), value.__delitem__(0))
            disabled(Disabled(events), events)
            static = Static()
            return repr((events, first, second, explicit, setitem(static, 1, 2), delitem(static, 1)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_setitem_retains_fresh_value_destination_context(optimize):
    result = LLVM().assert_matches_python('''
        from operator import setitem
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Items:
            def __init__(self): self.values: list[int8] = []
            def __setitem__(self, key: int, value: list[int8]) -> list[int8]:
                gc_collect()
                self.values = value
                return value
        def main() -> str:
            gc_set_threshold(1)
            rows = [[int8(1)]]
            setitem(rows, 0, [127])
            rows[0][0] += int8(1)
            plain = [[1]]
            setitem(plain, 0, [])
            mapping: dict[str, list[int]] = {}
            setitem(mapping, "new", [])
            items = Items()
            first = setitem(items, 0, [127])
            items.values[0] += int8(1)
            saved = items.values
            second = setitem(items, 0, [])
            return repr((rows, plain, mapping, saved, items.values, first, second))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("operation", ['row["values"] = []', 'row.__setitem__("values", [])',
                                       'setitem(row, "values", [])'])
def test_operator_setitem_keeps_existing_typed_dict_mutation_boundary(operation):
    with pytest.raises(CompilationError, match="Attribute '__setitem__' is not defined on 'Row'"):
        transpile_llvm(f'''from typing import TypedDict
from operator import setitem
class Row(TypedDict):
    values: list[int]
def main() -> str:
    row: Row = {{"values": [1]}}
    {operation}
    return repr(row)
''')


@pytest.mark.parametrize("operation, signature", [
    ("setitem(value, 0, 1)", "Callable[[int, int], int]"),
    ("delitem(value, 0)", "Callable[[int], int]"),
])
def test_operator_mutation_requires_an_actual_class_protocol(operation, signature):
    name = "__setitem__" if operation.startswith("setitem") else "__delitem__"
    with pytest.raises(CompilationError, match=f"class-level instance or static {name}") as caught:
        transpile_llvm(f'''from operator import setitem, delitem
from collections.abc import Callable
def setter(key: int, value: int) -> int: return 1
def deleter(key: int) -> int: return 2
class Fields:
    def __init__(self): self.{name}: {signature} = {"setter" if name == "__setitem__" else "deleter"}
def main() -> object:
    value = Fields()
    return {operation}
''', filename="item_protocol.py")
    assert caught.value.lineno == 9


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_item_mutation_preserves_order_none_and_recovery(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Items:
            def __init__(self, events: list[str]):
                self.events = events
                self.values = [1, 2, 3]
            def __setitem__(self, key: int, value: int) -> int:
                self.events.append("set")
                gc_collect()
                self.values[key] = value
                return 99
            def __delitem__(self, key: int) -> int:
                self.events.append("del")
                gc_collect()
                del self.values[key]
                return 100
        def receiver(events: list[str], value: Items) -> Items:
            events.append("receiver")
            return value
        def argument(events: list[str], name: str, value: int) -> int:
            events.append(name)
            gc_collect()
            return value
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            items = Items(events)
            a = op.setitem(receiver(events, items), argument(events, "key", 1), argument(events, "value", 7))
            b = op.delitem(receiver(events, items), argument(events, "key", 0))
            try: op.setitem(items, 20, 1)
            except IndexError: events.append("caught-set")
            try: op.delitem(items, 20)
            except IndexError: events.append("caught-del")
            op.setitem(items, 0, 8)
            values = [int8(1), int8(2)]
            c = op.setitem(values, 0, int8(127))
            d = op.delitem(values, -1)
            mapping = {"x": 1}
            op.setitem(mapping, "y", 2)
            op.delitem(mapping, "x")
            mapped = list(map(op.setitem, [values], [0], [int8(2)]))
            removed = list(map(op.delitem, [mapping], ["y"]))
            return repr((items.values, events, a, b, values, c, d, mapping, mapped, removed))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_concat_builtin_slots_aliases_representations_and_iterables(optimize):
    result = LLVM().assert_matches_python('''
        from operator import concat, iconcat
        from functools import reduce
        from itertools import accumulate
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def arguments(events: list[int], number: int) -> list[int]:
            events.append(number)
            gc_collect()
            return [number]
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = concat(arguments(events, 1), arguments(events, 2))
            alias = values
            extended = iconcat(values, (3, 4))
            original = [int8(127)]
            small = concat(original, [int8(-128)])
            iconcat(small, [int8(2)])
            combined = (concat((1, 2), (3, 4)), concat("ship", "master"),
                        concat(b"py", b"js"), iconcat("a", "b"),
                        iconcat(b"a", b"b"), iconcat((1,), (2,)))
            reduced = reduce(concat, [[1], [2], [3]])
            totals = list(accumulate([[1], [2]], concat))
            return repr((values, alias is extended, events, original, small, combined, reduced, totals))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_mutation_slices_index_callbacks_and_gc_roots(optimize):
    result = LLVM().assert_matches_python('''
        from operator import setitem, delitem
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int, events: list[int]):
                self.value, self.events = value, events
            def __index__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                return self.value
        def replacement(owners: list[list[int]], retained: list[int]) -> list[int]:
            owners.clear()
            gc_collect()
            return retained
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = [0, 1, 2, 3, 4]
            setitem(values, Index(-1, events), 9)
            delitem(values, Index(1, events))
            setitem(values, slice(1, 3), [7, 8, 10])
            delitem(values, slice(None, None, 2))
            owners = [[1, 2, 3]]
            retained = owners[0]
            result = setitem(owners[0], slice(1, 2), replacement(owners, retained))
            try: setitem(values, slice(None, None, 2), [1, 2, 3, 4])
            except ValueError: events.append(99)
            try: delitem(values, slice(None, None, 0))
            except ValueError: events.append(100)
            return repr((values, retained, owners, result, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_concat_fixed_tuple_shapes_empty_identity_and_portable_fields(optimize):
    result = LLVM().assert_matches_python('''
        from operator import concat, iconcat
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int): self.value = value
        def empty(events: list[int]) -> tuple[()]:
            events.append(1)
            gc_collect()
            return ()
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            left = (int8(127), "left")
            right = (float32(1.5), Value(7))
            result = concat(left, right)
            prefix = concat(empty(events), left)
            suffix = iconcat(right, empty(events))
            gc_collect()
            return repr((int(result[0] + int8(1)), result[1], result[2], result[3].value,
                         prefix is left, suffix is right, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("body, message", [
    ("return concat(1, 2)", "concrete builtin sequence receiver"),
    ("return iconcat(1, 2)", "concrete builtin sequence receiver"),
    ("return concat((1,), [2])", "another tuple"),
    ("values = StaticArray[int, 2]([1, 2])\n    return iconcat(values, [3])", "whole-array augmented"),
])
def test_operator_concat_diagnoses_unsupported_receivers_and_shape_changes(body, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm(f'''from operator import concat, iconcat
from pyjs import StaticArray
def main() -> object:
    {body}
''', filename="operator_concat.py")
    assert caught.value.lineno >= 4


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_item_and_concat_allocation_failures_leave_valid_inputs(tmp_path, optimize):
    source = transpile_llvm('''
        from operator import setitem, delitem, concat, iconcat
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        def operation(values: list[int], mapping: dict[str, int]) -> list[int]:
            setitem(values, 0, 7)
            setitem(mapping, "next", 8)
            result = concat(values, [3, 4])
            iconcat(values, result)
            delitem(mapping, "first")
            delitem(values, 1)
            return result
        def main() -> int:
            gc_set_threshold(1)
            failures = 0
            exhausted = False
            for stage in range(1, 200):
                values = [1, 2]
                mapping = {"first": 1}
                try:
                    arm(stage)
                    result = operation(values, mapping)
                    exhausted = remaining() > 0
                    arm(0)
                    assert result == [7, 2, 3, 4]
                    assert values == [7, 7, 2, 3, 4] and mapping == {"next": 8}
                except MemoryError:
                    arm(0)
                    failures += 1
                    assert values[0] == 7
                    assert len(values) >= 2
                finally:
                    arm(0)
                gc_collect()
                # Mutated prefixes need not roll back; the containers must
                # remain well formed and support subsequent mutations.
                setitem(values, 0, 9)
                setitem(mapping, "recovered", 10)
                assert values[0] == 9 and mapping["recovered"] == 10
                if exhausted: break
            assert exhausted and failures > 0
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
