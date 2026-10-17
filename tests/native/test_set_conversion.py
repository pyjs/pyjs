import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import SET_CONSTRUCTOR_REPRESENTATION_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_represented_union_iterables_work_for_nonset_consumers(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def show(values: Iterable[int8 | None]) -> str:
            return repr(sorted('None' if value is None else repr(value + 1) for value in values))
        def main() -> str:
            gc_set_threshold(1)
            source = [int8(1), int8(127)]
            target: list[int8 | None] = [None]
            target.extend(source)
            target.extend(set(source))
            target.extend(value for value in source)
            target[1:2] = source
            gc_collect()
            records = [show(target), show(source), show(set(source)), show(tuple(source)),
                       show({value: 'key' for value in source}), show(value for value in source)]
            source[1] += 1
            records.append(repr(source))
            records.append(show(target))
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["target.extend(source)", "target[1:2] = source", "consume(source)"])
def test_nonset_union_consumers_reject_conflicting_representations(expression):
    with pytest.raises(CompilationError, match="incompatible.*representation"):
        transpile_llvm(f'''
            from collections.abc import Iterable
            from pyjs import int8, int16
            def consume(values: Iterable[int8 | None]) -> int:
                return sum(1 for value in values)
            def main() -> int:
                target: list[int8 | None] = [None]
                source = [int16(127)]
                {expression}
                return len(target)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_explicit_set_constructor_representation(tmp_path, optimize):
    result = LLVM().assert_matches_python(SET_CONSTRUCTOR_REPRESENTATION_CONTRACT.source,
        directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, SET_CONSTRUCTOR_REPRESENTATION_CONTRACT.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_set_copies_and_algebra_preserve_values_and_aliases(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def show(values: Iterable[int8 | None]) -> str:
            return repr(sorted("None" if value is None else repr(value + 1) for value in values))

        def main() -> str:
            gc_set_threshold(1)
            items = [int8(0), int8(127)]
            source = set(items)
            mapping = {value: "present" for value in items}
            frozen = frozenset(source)
            records = [show(set[int8 | None](items)), show(set[int8 | None](source)),
                       show(set[int8 | None](mapping)), show(set[int8 | None](frozen))]
            expanded = {None, *items}
            records.append(show(expanded))
            singleton: set[int8 | None] = {None}
            singleton.add(int8(127))
            records.append(show(singleton))
            wide: set[int8 | None] = {None, int8(0)}
            records.extend([show(wide.union(source)), show(wide.intersection(source)),
                            show(wide.difference(source)), show(wide.symmetric_difference(source)),
                            show(wide | source), show(wide & source), show(wide - source), show(wide ^ source)])
            immutable = frozenset(wide)
            records.extend([show(immutable.union(source)), show(immutable.intersection(source)),
                            show(immutable.difference(source)), show(immutable.symmetric_difference(source)),
                            show(immutable | source), show(immutable & source), show(immutable - source),
                            show(immutable ^ source), show(immutable.copy())])
            records.append(repr((wide.issubset(source), wide.issuperset(source),
                                 wide.isdisjoint(source), wide <= source, wide >= source, wide == source)))
            for mode in range(8):
                target: set[int8 | None] = {None, int8(0)}
                alias = target
                if mode == 0:
                    target.update(source)
                elif mode == 1:
                    target.intersection_update(source)
                elif mode == 2:
                    target.difference_update(source)
                elif mode == 3:
                    target.symmetric_difference_update(source)
                elif mode == 4:
                    target |= source
                elif mode == 5:
                    target &= source
                elif mode == 6:
                    target -= source
                else:
                    target ^= source
                gc_collect()
                assert target is alias
                records.append(show(alias))
            assert sorted(source) == items and len(mapping) == 2 and len(frozen) == 2
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "set[int16 | None](source)",
    "frozenset[int16 | None](source)",
    "set[int](source)",
    "frozenset[int](source)",
    "target.update(source)",
    "target.__ior__(set(source))",
    "int8(1) in target",
    "frozenset(source) == frozenset([int16(1)])",
    "frozenset(source) <= frozenset([int16(1)])",
    "accept(set(source))",
])
def test_set_copying_does_not_change_numeric_widths_or_widen_mutable_aliases(expression):
    with pytest.raises(CompilationError, match="representation|represented"):
        transpile_llvm(f'''
            from pyjs import int8, int16

            def accept(value: set[int8 | None]) -> None:
                value.add(None)

            def main() -> int:
                source = [int8(1)]
                target: set[int16 | None] = {{None}}
                {expression}
                return 0
        ''')


def test_set_copying_does_not_erase_boolean_identity_into_integer_slots():
    with pytest.raises(LLVMUnsupported, match="requires a declared union member's storage"):
        transpile_llvm('''
            def main() -> int:
                target: set[int | None] = {None}
                target.update([True])
                return len(target)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_heterogeneous_primitive_set_comparisons_use_python_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def main() -> str:
            wide: set[int | None] = {None, 1}
            integers = {1}
            floats = {1.0}
            booleans = {True}
            absent: set[int | None] = {None}
            zero = {0}
            return repr((wide >= floats, wide > booleans, floats < wide, integers <= wide,
                         integers == floats, floats == booleans, absent == zero, absent <= zero,
                         zero >= absent, wide == floats))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_converted_intersections_keep_operand_payloads_and_representations(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from pyjs import float32, int8
        from pyjs.native import gc_collect, gc_set_threshold

        def show(values: Iterable[float | None]) -> str:
            return repr(sorted(repr(value) for value in values))

        def main() -> str:
            gc_set_threshold(1)
            left: set[float | None] = {None, -0.0}
            right = {0.0}
            records = [show(left.intersection(right)), show(left & right)]
            equal: set[float | None] = {-0.0}
            records.append(show(equal.intersection(right)))
            larger = {0.0, 1.0}
            records.append(show(equal.intersection(larger)))
            numbers: set[int8 | None] = {None, int8(127)}
            first: set[int8 | None] = {None, int8(127)}
            last = {int8(127)}
            copied = numbers.intersection(first, last)
            alias = numbers
            numbers.intersection_update(first, last)
            gc_collect()
            assert numbers is alias
            for item in copied:
                if item is not None:
                    records.append(repr(item + 1))
            for item in numbers:
                if item is not None:
                    records.append(repr(item + 1))
            floats: set[float32 | None] = {None, float32(16777216.0)}
            floating = floats.intersection({None, float32(16777216.0)}, {float32(16777216.0)})
            for float_item in floating:
                if float_item is not None:
                    records.append(repr(float_item + 1.0))
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["scratch", "gc"])
def test_converted_set_allocation_failures_preserve_aliases_and_allow_retry(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs import int8
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def main() -> int:
            items = [int8(index) for index in range(7)]
            source = set(items)
            for mode in range({4 if managed else 3}):
                stages = 1
                failure = 0
                while failure <= stages:
                    target: set[int8 | None] = {{None, int8(0)}}
                    alias = target
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        if mode == 0:
                            target.update(source)
                        elif mode == 1:
                            target.update(items)
                        elif mode == 2:
                            target.intersection_update(source)
                        else:
                            target = set[int8 | None](source)
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if stages < 1:
                        return 20 + mode
                    if caught != (failure != 0):
                        return 30 + mode
                    if (mode != 3 or caught) and target is not alias:
                        return 2
                    if caught and mode >= 2 and (len(alias) != 2 or None not in alias):
                        return 3
                    for value in alias:
                        if value is not None and value not in source:
                            return 4
                    if len(source) != 7:
                        return 5
                    alias.update(source)
                    if len(alias) != (7 if mode == 2 and not caught else 8):
                        return 6
                    failure += 1
            return 0
    ''')
    # Iterable contracts enable the managed heap. The scratch-only pass faults
    # temporary/backing allocations; fresh construction needs the GC pass.
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("item_type", "items"), [
    ("str", '["zero", "one"]'),
    ("bytes", '[b"zero", b"one"]'),
    ("bool", "[False, True]"),
    ("float", "[0.0, 1.25]"),
    ("float32", "[float32(0.0), float32(1.25)]"),
    ("int64", "[int64(0), int64(9007199254740993)]"),
    ("int | str", '[0, "one"]'),
    ("int64 | str", '[int64(9007199254740993), "one"]'),
])
def test_set_conversion_preserves_primitive_domains_and_lazy_inputs(tmp_path, optimize, item_type, items):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterable, Iterator
        from pyjs import float32, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def show(values: Iterable[{item_type} | None]) -> str:
            return repr(sorted(repr(value) for value in values))

        def lazy(items: list[{item_type}]) -> Iterator[{item_type}]:
            for item in items:
                gc_collect()
                yield item

        def main() -> str:
            gc_set_threshold(1)
            items = {items}
            source = set(items)
            copied = set[{item_type} | None](source)
            frozen = frozenset[{item_type} | None](source)
            source.clear()
            gc_collect()
            records = [show(copied), show(frozen)]
            for mode in range(4):
                wide: set[{item_type} | None] = {{None, items[0]}}
                alias = wide
                if mode == 0:
                    wide.update(lazy(items))
                elif mode == 1:
                    wide.intersection_update(lazy(items))
                elif mode == 2:
                    wide.difference_update(lazy(items))
                else:
                    wide.symmetric_difference_update(lazy(items))
                gc_collect()
                assert wide is alias
                records.append(show(alias))
            wide: set[{item_type} | None] = {{None, items[0]}}
            records.extend([show(wide.intersection(source)), show(wide.intersection(set(items))),
                            repr(wide.isdisjoint(lazy(items))), repr(wide.issuperset(lazy(items))),
                            repr(wide.issubset(lazy(items)))])
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
