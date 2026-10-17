import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    COLLECTION_NAME_CONTRACT,
    NUMERIC_NAME_CONTRACT,
    TUPLE_ITERABLE_CONTRACT,
    nominal_alias_comparison_contract,
    nominal_constructor_contract,
    nominal_object_contract,
    nominal_truth_contract,
    nominal_union_comparison_contract,
    scalar_namesake_sort_contract,
)


@pytest.mark.parametrize("contract", [COLLECTION_NAME_CONTRACT, TUPLE_ITERABLE_CONTRACT, NUMERIC_NAME_CONTRACT])
def test_application_collection_names(tmp_path, contract):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)


@pytest.mark.parametrize("name", ["int", "float", "bool"])
def test_numeric_named_host_records_keep_reference_storage(tmp_path, name):
    library = LLVM().compile_library(f'''
        class {name}:
            def __init__(self, text: str):
                self.text = text
        def render(values: list[{name}]) -> str:
            return values[0].text
    ''', tmp_path, entry_point="render")
    try:
        assert library.render([{"text": "record—not a scalar"}]) == "record—not a scalar"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_name_union_narrowing_with_sanitizers(tmp_path, optimize):
    result = LLVM().assert_matches_python(NUMERIC_NAME_CONTRACT.source, directory=tmp_path,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, NUMERIC_NAME_CONTRACT.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["int", "float", "bool", "str", "bytes"])
def test_scalar_namesake_sorting_uses_application_comparisons(tmp_path, optimize, name):
    contract = scalar_namesake_sort_contract(name)
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["int", "float", "bool", "str", "bytes", "list", "tuple", "dict", "set", "frozenset", "range", "object"])
def test_erased_and_searched_records_keep_nominal_identity(tmp_path, optimize, name):
    contract = nominal_object_contract(name)
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["Base", "object"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_nominal_comparison_across_union_arms(tmp_path, optimize, name):
    contract = nominal_union_comparison_contract(name)
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["Base", "object"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_nominal_optional_comparison_keeps_application_identity(tmp_path, name, optimize):
    result = LLVM().assert_matches_python(nominal_union_comparison_contract(name, optional=True).source,
                                         directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("name", ["Box", "object"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_root_equality_keeps_alias_callbacks_but_container_items_use_identity(tmp_path, name, optimize):
    contract = nominal_alias_comparison_contract(name)
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("contract", [
    *(nominal_constructor_contract(name) for name in ("Box", "dict", "list", "set", "frozenset", "tuple")),
    *(nominal_truth_contract(name) for name in ("Box", "bool")),
])
def test_nominal_construction_and_truth_keep_application_protocols(tmp_path, contract):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                         optimize=2, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["Box", "str", "int"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_namesake_search_callbacks_can_clear_the_parent_and_collect(tmp_path, name, optimize):
    result = LLVM().assert_matches_python(f'''
        from builtins import int as Integer, bool as Boolean, list as List
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, rank: Integer, owner: List["{name}"]):
                self.rank = rank
                self.owner = owner
            def __eq__(self, other: "{name}") -> Boolean:
                self.owner.clear()
                gc_collect()
                return self.rank == other.rank
        def search(mode: Integer) -> Integer:
            rows: List[{name}] = []
            rows.append({name}(1, rows))
            needle = {name}(1, [])
            if mode == 0:
                return 1 if needle in rows else 0
            if mode == 1:
                return rows.index(needle)
            if mode == 2:
                return rows.count(needle)
            rows.remove(needle)
            return len(rows)
        def main() -> Integer:
            gc_set_threshold(1)
            assert search(0) == 1
            assert search(1) == 0
            assert search(2) == 1
            assert search(3) == 0
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_application_append_keywords_are_not_builtin_ir(tmp_path):
    result = LLVM().assert_matches_python('''
        class list:
            def append(self, value: int) -> int:
                return value + 1
        def main() -> int:
            return list().append(value=41)
    ''', directory=tmp_path)
    assert result.native.returncode == 42


@pytest.mark.parametrize("name", ["Generator", "Iterator", "KeysView", "Source"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_application_names_do_not_select_builtin_consumers(tmp_path, name, optimize):
    # Application bytes protocols dispatch on the runtime class. An object
    # lacking those protocols raises TypeError, not a compile-time boundary.
    result = LLVM().assert_matches_python(f'''
            class {name}:
                def __init__(self, n: int):
                    self.n = n
                def __bool__(self) -> bool:
                    return self.n > 0
            def main() -> str:
                values = [{name}(0), {name}(1)]
                try:
                    return repr(bytes(values[0]))
                except TypeError:
                    return "TypeError"
        ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_iterator_upcasts_preserve_virtual_dispatch(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Generator:
            def __init__(self, n: int):
                self.n = n
            def size(self) -> int:
                return self.n
        class Iterator(Generator):
            def size(self) -> int:
                gc_collect()
                return self.n * 2
        def main() -> str:
            gc_set_threshold(1)
            value: Generator = Iterator(3)
            values: list[Generator] = [Generator(1), Iterator(2)]
            return repr([value.size()] + [item.size() for item in values])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["Generator", "Iterator", "KeysView", "Source"])
def test_truth_consumers_select_runtime_protocols(tmp_path, optimize, name):
    # No explicit bool(Child()) call: implicit consumers must retain its method.
    result = LLVM().assert_matches_python(f'''
        from itertools import compress, filterfalse
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, events: list[int]):
                self.events = events
            def __len__(self) -> int:
                self.events.append(1)
                gc_collect()
                return 1
        class Child({name}):
            def __bool__(self) -> bool:
                self.events.append(2)
                gc_collect()
                return False
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values: list[{name}] = [Child(events), {name}(events), Child(events)]
            filtered = filter(None, values)
            assert events == []
            a = len(list(filtered))
            b = len(list(filterfalse(None, values)))
            c = list(compress(selectors=values, data=[10, 20, 30]))
            d = any(values)
            e = all(values)
            return repr((a, b, c, d, e, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_and_builtin_item_truth(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self, value: int):
                self.value = value
            def __bool__(self) -> bool:
                gc_collect()
                return self.value > 0
        def main() -> str:
            gc_set_threshold(1)
            numbers: list[int | None] = [None, 0, 2]
            items: list[Item | None] = [None, Item(0), Item(1)]
            empty: tuple[int, ...] = ()
            full: tuple[int, ...] = (1, 2)
            return repr((any(numbers), all(numbers), len(list(filter(None, numbers))),
                         any(items), all(items), len(list(filter(None, items))),
                         any([empty]), all([full]), any([range(0)]), all([range(2)])))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_truth_consumer_exceptions_and_short_circuit(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events
            def __len__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                return self.value
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = [Item(0, events), Item(1, events), Item(-1, events)]
            assert any(values) and not all(values)
            cursor = filter(None, values)
            assert next(cursor).value == 1
            try:
                next(cursor)
            except ValueError:
                events.append(9)
            try:
                all([Item(1, events), Item(-1, events)])
            except ValueError:
                events.append(8)
            # Both short-circuit and failure must leave a reusable live frame.
            gc_collect()
            assert next(cursor, None) is None
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("base", ["list[int]", "dict[int, int]", "tuple[int, int]", "tuple[int, ...]",
                                 "list[list[int]]", "str", "bytes", "set[int]", "frozenset[int]"])
def test_builtin_container_subclass_requires_supported_layout(base):
    with pytest.raises(LLVMUnsupported, match="subclasses of builtin containers"):
        transpile_llvm(f'''
            class Child({base}):
                pass
            def main() -> bool:
                return bool(Child())
        ''')


@pytest.mark.parametrize("operation", ["filter", "filterfalse"])
def test_nullable_predicate_has_a_focused_boundary(operation):
    with pytest.raises(LLVMUnsupported, match="narrow nullable predicates before use"):
        transpile_llvm(f'''
            from collections.abc import Callable
            from itertools import filterfalse
            def select(predicate: Callable[[int], bool] | None) -> int:
                return len(list({operation}(predicate, [0, 1])))
            def main() -> int:
                return select(None)
        ''')


def test_explicitly_narrowed_nullable_predicate(tmp_path):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        def select(predicate: Callable[[int], bool] | None) -> int:
            if predicate is None:
                return len(list(filter(None, [0, 1, 2])))
            return len(list(filter(predicate, [0, 1, 2])))
        def main() -> int:
            return select(None) + select(lambda value: value > 1)
    ''', directory=tmp_path)
    assert result.native.returncode == 3


@pytest.mark.parametrize("name", ["tuple", "frozenset"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_application_container_names_use_own_hash_and_iterable_protocols(tmp_path, name, optimize):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterator as Cursor
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, value: int):
                self.value = value
            def __hash__(self) -> int:
                gc_collect()
                return self.value
            def __repr__(self) -> str:
                gc_collect()
                return "key"
            def __eq__(self, other: {name}) -> bool:
                gc_collect()
                return self.value == other.value
            def __iter__(self) -> Cursor[int]:
                yield self.value
                gc_collect()
                yield self.value + 1
        def main() -> str:
            gc_set_threshold(1)
            value = {name}(5)
            mapping = {{value: 42}}
            members = {{value}}
            assert hash(value) == 5
            assert {name}(5) in members
            assert mapping[{name}(5)] == 42
            try:
                mapping[{name}(7)]
            except KeyError as error:
                assert str(error) == "key"
            return repr(([n for n in value], any(value), all(value)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["tuple", "frozenset"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_application_generic_parameter_is_not_its_iteration_item_type(tmp_path, name, optimize):
    # Application protocols yield int even when their own phantom T is str.
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterator as Cursor
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}[T]:
            def __init__(self, value: int):
                self.value = value
            def __iter__(self) -> Cursor[int]:
                yield self.value
                gc_collect()
                yield self.value + 1
        def main() -> str:
            gc_set_threshold(1)
            value = {name}[str](5)
            return repr(([n for n in value], any(value), all(value)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["tuple", "list", "frozenset"])
def test_collection_spelling_does_not_supply_an_iteration_protocol(name):
    with pytest.raises(CompilationError, match="iterable"):
        transpile_llvm(f'''
            class {name}:
                pass
            def main() -> int:
                return len([value for value in {name}()])
        ''')


@pytest.mark.parametrize("name", ["tuple", "frozenset", "set", "dict"])
@pytest.mark.parametrize("custom_keys", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_application_iterables_do_not_use_set_storage_shortcuts(tmp_path, name, custom_keys, optimize):
    key = "Key" if custom_keys else "int"
    projection = "item.value" if custom_keys else "item"
    constructor = "frozenset" if name == "set" else "set"
    source = f'''
        from collections.abc import Iterator as Cursor
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
            def __hash__(self) -> int:
                gc_collect()
                return self.value
            def __eq__(self, other: Key) -> bool:
                gc_collect()
                return self.value == other.value
        class {name}:
            def __init__(self, value: int):
                self.value = value
            def __iter__(self) -> Cursor[{key}]:
                yield {key}(self.value)
                gc_collect()
                yield {key}(self.value + 1)
        def main() -> str:
            gc_set_threshold(1)
            s = {{{key}(3), {key}(5)}}
            parts: list[list[int]] = []
    '''
    operations = [f"{constructor}({name}(3))", f"s.union({name}(3))",
                  f"s.intersection({name}(3))", f"s.difference({name}(3))",
                  f"s.symmetric_difference({name}(3))"]
    for operation in operations:
        source += f"\n            parts.append(sorted([{projection} for item in {operation}]))\n"
    source += f'''
            seed = {{{key}(0): 9}}
            mapping = seed.fromkeys({name}(3), 9)
            parts.append(sorted([{projection} for item in mapping]))
            flags = (s.issubset({name}(3)), s.issuperset({name}(3)), s.isdisjoint({name}(7)))
            s.update({name}(7))
            s.difference_update({name}(3))
            s.symmetric_difference_update({name}(7))
            s.intersection_update({name}(5))
            parts.append(sorted([{projection} for item in s]))
            return repr((parts, flags))
    '''
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["Bag", "tuple", "frozenset", "set", "dict", "list", "str", "bytes", "range", "KeysView"])
def test_len_does_not_read_application_objects_as_builtin_headers(tmp_path, name):
    result = LLVM().assert_matches_python(f'''
            class {name}:
                def __init__(self, value: int):
                    self.value = value
                def __len__(self) -> int:
                    return 2
            def main() -> int:
                return len({name}(9))
        ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.returncode == 2
    assert result.native.stderr == ""


@pytest.mark.parametrize("direct_loop", [False, True])
def test_union_iterable_has_a_focused_boundary(direct_loop):
    body = ("count = 0\n    for value in values:\n        count += value\n    return count"
            if direct_loop else "return len(list(filter(None, values)))")
    with pytest.raises(LLVMUnsupported, match="concrete.*iterable"):
        transpile_llvm("def select(values: list[int] | tuple[int, ...]) -> int:\n    " + body
                       + "\ndef main() -> int:\n    return select([0, 1])\n")


@pytest.mark.parametrize("name", ["tuple", "frozenset", "Bag"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_application_iterator_items_do_not_prepare_builtin_tuple_storage(tmp_path, name, optimize):
    result = LLVM().assert_matches_python(f'''
        from itertools import filterfalse, compress
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, value: int):
                self.value = value
            def __bool__(self) -> bool:
                gc_collect()
                return self.value != 0
        def main() -> str:
            gc_set_threshold(1)
            values = [{name}(0), {name}(3)]
            return repr(([item.value for item in filter(None, values)],
                         [item.value for item in filterfalse(None, values)],
                         [item.value for item in compress(values, [True, True])]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["tuple", "set", "frozenset"])
def test_application_default_equality_does_not_use_builtin_headers(tmp_path, name):
    result = LLVM().assert_matches_python(f'''
        class {name}:
            def __init__(self, value: int):
                self.value = value
        def main() -> str:
            value = {name}(3)
            return repr((({{3}},) == (value,), (value,) == ({{3}},),
                         ((3,),) == (value,), (value,) == ((3,),)))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["tuple", "set"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_application_builtin_ordering_keeps_runtime_type_errors(tmp_path, name, optimize):
    # Bilateral comparisons now support this shape, but must not interpret a
    # nominal namesake as a builtin container or invent an ordering for it.
    result = LLVM().assert_matches_python(f'''
            class {name}:
                def __init__(self, value: int):
                    self.value = value
            def main() -> str:
                try:
                    return str(((3,),) < ({name}(3),))
                except TypeError as error:
                    return str(error)
        ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["set", "frozenset", "Bag"])
@pytest.mark.parametrize("expression", ["s <= value", "s < value", "value >= s", "value > s", "value <= s"])
@pytest.mark.parametrize("warm", [False, True])
def test_application_receiver_does_not_select_builtin_set_ordering(tmp_path, name, expression, warm):
    # Reaching __iter__ used to change an internal dependency error into an
    # invalid set-header read. Bilateral comparison now implements the runtime
    # TypeError; neither a colliding name nor a reached iterator makes a set.
    comparison = LLVM().assert_matches_python(f'''
            from collections.abc import Iterator as Cursor
            class {name}:
                def __init__(self, value: int):
                    self.value = value
                def __iter__(self) -> Cursor[int]:
                    yield self.value
                    yield self.value + 1
            def main() -> str:
                value = {name}(3)
                {"sorted(value)" if warm else "pass"}
                s = {{3}}
                try:
                    return repr({expression})
                except TypeError as error:
                    return str(error)
        ''', directory=tmp_path, optimize=2, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["set", "frozenset", "dict", "Bag"])
@pytest.mark.parametrize("expression", [
    "left(events, stage == 1) < right(events, stage == 2)",
    "left(events, stage == 1) in right(events, stage == 2)",
    "left(events, stage == 1) not in right(events, stage == 2)",
    "left(events, stage == 1) + right(events, stage == 2)",
    "right(events, stage == 2).__gt__(left(events, stage == 1))",
], ids=["reflected", "membership", "not-membership", "reflected-add", "explicit"])
def test_application_operator_operands_run_once_in_source_order(tmp_path, optimize, name, expression):
    result = LLVM().assert_matches_python(f'''
        from typing import Set
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, events: list[int]):
                self.events = events
            def __gt__(self, other: Set[int]) -> bool:
                self.events.append(3)
                gc_collect()
                return 7 in other
            def __contains__(self, other: Set[int]) -> bool:
                return self.__gt__(other)
            def __radd__(self, other: Set[int]) -> int:
                return 7 if self.__gt__(other) else 0
        def left(events: list[int], fail: bool) -> Set[int]:
            events.append(1)
            gc_collect()
            if fail:
                raise ValueError("left")
            return {{7}}
        def right(events: list[int], fail: bool) -> {name}:
            events.append(2)
            gc_collect()
            if fail:
                raise ValueError("right")
            return {name}(events)
        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            for stage in range(3):
                events: list[int] = []
                try:
                    matched = {expression}
                    results.append(str(matched))
                except ValueError:
                    results.append("failed")
                results.append(repr(events))
            return "|".join(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_application_tuple_infers_sorted_and_fromkeys_items(tmp_path):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator as Cursor
        class tuple:
            def __iter__(self) -> Cursor[int]:
                return iter([3, 4])
        def main() -> str:
            return repr((sorted(tuple(), key=lambda value: -value), dict.fromkeys(tuple(), 9)))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["tuple", "list", "Bag"])
def test_text_join_consumes_application_iterables(tmp_path, name):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterator
        class {name}:
            def __iter__(self) -> Iterator[str]:
                return iter(["a", "b"])
        def main() -> str:
            return "-".join({name}())
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", ["value.__str__()", "str(value)", "repr(value)", 'f"{value}"', "repr([value])"])
def test_application_nonetype_name_has_a_focused_boundary(expression):
    with pytest.raises(LLVMUnsupported, match="application classes named NoneType.*rename the class"):
        transpile_llvm(f'''
            class NoneType:
                pass
            def main() -> str:
                value = NoneType()
                return {expression}
        ''')


@pytest.mark.parametrize("name", ["str", "bytes", "float", "bool", "list", "range", "Bag"])
def test_inherited_object_method_does_not_select_builtin_receiver_storage(tmp_path, name):
    result = LLVM().assert_matches_python(f'''
        class {name}:
            def __init__(self, value: int):
                self.value = value
        def main() -> int:
            text = {name}(3).__str__()
            return int(not text.startswith("<") or "{name}" not in text)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["Generator", "Iterator", "KeysView", "range"])
def test_application_truth_precedes_builtin_layouts(tmp_path, optimize, name):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, n: int):
                self.n = n
            def __len__(self) -> int:
                gc_collect()
                return self.n
        def main() -> str:
            gc_set_threshold(1)
            values = [{name}(0), {name}(1)]
            return repr(([bool(value) for value in values],
                         [value.n for value in values if value],
                         any(bool(value) for value in values),
                         all(bool(value) for value in values)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
