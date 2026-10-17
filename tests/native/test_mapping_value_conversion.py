import subprocess

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations, run_allocation_case


@pytest.mark.parametrize("operation", ["left | right", "left.__or__(right)", "left.__ror__(right)",
                                      "left.__ior__(right)", "left |= right"])
def test_mapping_union_rejects_conflicting_portable_widths(operation):
    with pytest.raises(CompilationError, match="Stored mapping items use incompatible representations"):
        transpile_llvm(f'''
            from pyjs import int8, int16
            def main() -> int:
                left = {{1: int8(127)}}
                right = {{2: int16(128)}}
                {operation}
                return len(left)
        ''')


@pytest.mark.parametrize("method", ["__or__", "__ror__", "__ior__"])
def test_mapping_union_dunders_require_positional_arguments(method):
    with pytest.raises(CompilationError, match="parameter 'other' is positional-only"):
        transpile_llvm(f'''
            def main() -> int:
                left = {{1: 2}}
                return len(left.{method}(other={{3: 4}}))
        ''')


@pytest.mark.parametrize(("left", "right"), [
    ('left: dict[str, int] = {"x": 1}', '{"y": True}'),
    ('left: dict[str, list[int | None]] = {"x": [None]}', '{"y": [1]}'),
])
def test_mapping_union_does_not_erase_boolean_identity_or_widen_mutable_values(left, right):
    with pytest.raises(LLVMUnsupported, match="compatible value layouts"):
        transpile_llvm(f'''
            def main() -> int:
                {left}
                right = {right}
                result = left | right
                return len(result)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_readonly_mapping_union_converts_values_in_both_operand_orders(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, number: int, events: list[int]):
                self.number = number
                self.events = events
                self.hashed = False
                self.fail = False

            def __hash__(self) -> int:
                if self.hashed:
                    raise ValueError("rehashed")
                self.hashed = True
                return 1

            def __eq__(self, other: object) -> bool:
                self.events.append(self.number)
                gc_collect()
                if self.fail:
                    raise ValueError("comparison failed")
                return isinstance(other, Key) and self.number == other.number

        def show(values: dict[Key, int8 | None]) -> str:
            return repr([(key.number, None if value is None else value + 1)
                         for key, value in values.items()])

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            original = Key(1, events)
            other = Key(1, events)
            wide: dict[Key, int8 | None] = {original: None, Key(2, events): int8(-128)}
            narrow = {other: int8(127), Key(3, events): int8(2)}
            records: list[str] = []
            for mode in range(4):
                events.clear()
                if mode == 0:
                    result = wide | narrow
                elif mode == 1:
                    result = narrow | wide
                elif mode == 2:
                    result = wide.__or__(narrow)
                else:
                    result = wide.__ror__(narrow)
                gc_collect()
                records.extend([show(result), repr(events)])
                assert list(result)[0] is (original if mode % 2 == 0 else other)
                assert result is not wide and result is not narrow
            assert len(wide) == 2 and len(narrow) == 2
            original.fail = True
            saved = wide
            try:
                saved = wide | narrow
                raise AssertionError("comparison did not fail")
            except ValueError as error:
                records.append(str(error))
            assert saved is wide
            original.fail = False
            gc_collect()
            records.append(show(wide | narrow))
            nullable: dict[str, int8 | None] = {"x": None}
            numbers = {"x": int8(127), "y": int8(-128)}
            for primitive_result in (nullable | numbers, numbers | nullable):
                records.append(repr([None if value is None else value + 1
                                     for value in primitive_result.values()]))
            tagged_numbers: dict[str, int64 | str] = {"label": "wide"}
            exact_numbers = {"number": int64(2**60 + 1)}
            for exact_result in (tagged_numbers | exact_numbers, exact_numbers | tagged_numbers):
                records.append(repr([value + 1 if isinstance(value, int) else value
                                     for value in exact_result.values()]))
            shared = [int8(127)]
            pointers = {Key(4, events): shared}
            tagged: dict[Key, list[int8] | int] = {Key(5, events): 7}
            joined = tagged | pointers
            pointers.clear()
            tagged.clear()
            gc_collect()
            shared.append(int8(-128))
            for item in joined.values():
                if isinstance(item, list):
                    assert item is shared
                    records.append(repr([value + 1 for value in item]))
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_converted_mapping_copies_preserve_cached_hashes_and_numeric_domains(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, number: int, events: list[int]):
                self.number = number
                self.events = events
                self.hashed = False

            def __hash__(self) -> int:
                if self.hashed:
                    raise ValueError("rehashed")
                self.hashed = True
                return 1

            def __eq__(self, other: object) -> bool:
                self.events.append(self.number)
                gc_collect()
                return isinstance(other, Key) and self.number == other.number

        def show(values: dict[Key, int8 | None]) -> str:
            return repr([None if value is None else value + 1 for value in values.values()])

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            source = {Key(1, events): int8(127), Key(2, events): int8(-128)}
            events.clear()
            empty: dict[Key, int8 | None] = {}
            empty.update(source)
            records = [show(empty), repr(events)]
            occupied: dict[Key, int8 | None] = {Key(1, events): None}
            events.clear()
            occupied.update(source)
            records.extend([show(occupied), repr(events)])
            # Both augmented syntax and the explicit in-place dunder preserve
            # the destination identity and the represented values being copied.
            assert occupied.__ior__(source) is occupied
            occupied |= source
            records.append(show(occupied))
            events.clear()
            expanded = {**source, Key(3, events): None}
            records.extend([show(expanded), repr(events)])
            source.clear()
            gc_collect()
            records.append(show(empty))
            numbers = {1: int8(127), 2: int8(-128)}
            numbered: dict[int, int8 | None] = {3: None}
            numbered.update(numbers)
            records.append(repr([None if value is None else value + 1 for value in numbered.values()]))
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_union_same_layout_and_application_results(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Mask:
            def __or__(self, other: int) -> dict[str, int8]:
                return {"mask": int8(other)}
            def __ror__(self, other: int) -> dict[str, int8]:
                return {"reflected": int8(other)}

        def main() -> str:
            gc_set_threshold(1)
            left = {"a": int8(127), "b": int8(-128)}
            right = {"b": int8(4), "c": int8(5)}
            records: list[str] = []
            for mapping in (left | right, left.__ror__(right), left | left,
                            Mask() | 127, 127 | Mask()):
                gc_collect()
                records.append(repr([(key, value + 1) for key, value in mapping.items()]))
            assert left == {"a": int8(127), "b": int8(-128)}
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_converted_mapping_union_allocation_failures_do_not_publish_results(
    tmp_path, optimize, managed,
):
    source = transpile_llvm('''
        from pyjs import int8
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def main() -> int:
            for reverse in (False, True):
                stages = 1
                failure = 0
                while failure <= stages:
                    # Tracking metadata is lazy: each fault trial needs the
                    # same cold sources as the successful allocation count.
                    wide: dict[int, int8 | None] = {0: None}
                    narrow = {index: int8(index + 126) for index in range(6)}
                    result = wide
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        result = narrow | wide if reverse else wide | narrow
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    gc_collect()
                    if stages < 3 or caught != (failure != 0):
                        return 1
                    if len(wide) != 1 or wide[0] is not None or len(narrow) != 6:
                        return 2
                    if caught and result is not wide:
                        return 3
                    result = narrow | wide if reverse else wide | narrow
                    gc_collect()
                    if len(result) != 6 or result is wide or result is narrow:
                        return 4
                    if result[0] != (None if reverse else int8(126)):
                        return 5
                    if result[2] != int8(-128):
                        return 6
                    failure += 1
            return 0
    '''.replace("gc_collect()", "gc_collect()" if managed else "pass"))
    executable = LLVM().compile(
        _fail_allocations(source, managed), tmp_path, optimize=optimize,
    )
    result = subprocess.run([executable], capture_output=True, timeout=5)
    assert result.returncode == 0, (result.returncode, result.stderr)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_converted_mapping_allocation_failures_preserve_entries_and_allow_retry(
    tmp_path, optimize, managed,
):
    source = transpile_llvm(f'''
        from pyjs import int8
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        class Key:
            def __init__(self, number: int):
                self.number = number
                self.hashed = False

            def __hash__(self) -> int:
                if self.hashed:
                    raise ValueError("rehashed")
                self.hashed = True
                return 1

            def __eq__(self, other: object) -> bool:
                return isinstance(other, Key) and self.number == other.number

        def main() -> int:
            expected: list[int8 | None] = [int8(126), int8(127), int8(-128),
                                          int8(-127), int8(-126), int8(-125)]
            for occupied in (False, True):
                stages = 1
                failure = 0
                while failure <= stages:
                    # Do not reuse a source warmed by an earlier successful
                    # copy when measuring cold order-tracking allocations.
                    source = {{Key(index): int8(index + 126) for index in range(6)}}
                    target: dict[Key, int8 | None] = {{}}
                    if occupied:
                        target[Key(0)] = None
                    alias = target
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        target.update(source)
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if stages < 3 or caught != (failure != 0):
                        return 1
                    index = 0
                    for item in alias.values():
                        # Failure while preparing source metadata can happen
                        # before replacing the destination's existing value.
                        untouched = occupied and caught and index == 0 and len(alias) == 1 and item is None
                        if not untouched and item != expected[index]:
                            return 2
                        index += 1
                    if len(source) != 6:
                        return 3
                    target.update(source)
                    if len(alias) != len(expected):
                        return 4
                    index = 0
                    for item in alias.values():
                        if item != expected[index]:
                            return 5
                        index += 1
                    failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
