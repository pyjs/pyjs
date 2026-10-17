import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_callbacks_preserve_expression_conversion_and_mutation_order(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Bound:
            def __init__(self, value: int, marker: int, values: list[int], events: list[int]):
                self.value, self.marker = value, marker
                self.values, self.events = values, events
            def __index__(self) -> int:
                self.events.append(self.marker)
                self.values.append(self.marker)
                gc_collect()
                if self.value == 99:
                    raise ValueError("bad index")
                return self.value
        def bound(value: int, marker: int, values: list[int], events: list[int]) -> Bound:
            events.append(-marker)
            return Bound(value, marker, values, events)
        def receiver(values: list[int], events: list[int]) -> list[int]:
            events.append(50)
            return values
        def replacement(events: list[int]) -> list[int]:
            events.append(60)
            return [8, 9]
        def main() -> str:
            gc_set_threshold(1)
            values = [0, 1, 2, 3]
            events: list[int] = []
            rows = [repr(receiver(values, events)[bound(1, 1, values, events):
                      bound(20, 2, values, events):bound(2, 3, values, events)])]
            receiver(values, events)[bound(1, 4, values, events):
                bound(3, 5, values, events):bound(1, 6, values, events)] = replacement(events)
            del receiver(values, events)[bound(1, 7, values, events):
                bound(5, 8, values, events):bound(2, 9, values, events)]
            rows.append(repr(values))
            for step in [0, 99, 1]:
                try:
                    values[bound(99, 10, values, events):bound(2, 11, values, events):
                           bound(step, 12, values, events)]
                except ValueError as error:
                    rows.append(str(error))
            try:
                values[bound(1, 13, values, events):bound(99, 14, values, events):
                       bound(1, 15, values, events)] = replacement(events)
            except ValueError as error:
                rows.append(str(error))
            try:
                del values[bound(1, 16, values, events):bound(99, 17, values, events):
                           bound(1, 18, values, events)]
            except ValueError as error:
                rows.append(str(error))
            rows.append(repr(values))
            rows.append(repr(events))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_callbacks_retain_temporaries_optional_erased_and_reached_overrides(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Index(Base):
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        def base(value: Base) -> str:
            return ('aé😀' * 3)[value:]
        def optional(value: Index | None) -> str:
            return repr(([0, 1, 2, 3][value:], (0, 1, 2, 3)[::value],
                         b'abcdef'[value:], range(10)[value::value]))
        def erased(start: object, stop: object, step: object) -> str:
            return repr(([0, 1, 2, 3][start:stop:step], 'aé😀é'[start:stop:step]))
        def main() -> str:
            gc_set_threshold(1)
            rows = [base(Index(1)), optional(Index(2)), optional(None),
                    erased(Index(1), None, Index(2)), erased(None, Index(3), -1),
                    repr(()[Index(2)::Index(-1)])]
            try:
                base(Base())
            except TypeError as error:
                rows.append(str(error))
            try:
                erased('bad', None, None)
            except TypeError as error:
                rows.append(str(error))
            try:
                ()[Index(2)::Index(0)]
            except ValueError as error:
                rows.append(str(error))
            gc_collect()
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_refined_slice_receivers_use_checked_bound_conversion(optimize):
    # PR116 I7: these receiver forms bypassed the old builtin-class guard.
    result = LLVM().assert_matches_python('''
        from enum import StrEnum
        from typing import Literal
        class Index:
            def __index__(self) -> int:
                return 2
        class Color(StrEnum):
            RED = "crimson"
            BLUE = "navy"
        class Box:
            def __init__(self, color: Color):
                self.color = color
        def literal(text: Literal['abcdef', 'uvwxyz'], bound: int | Index | str) -> str:
            return text[bound:]
        def attribute(box: Box, bound: int | Index | str) -> str:
            return box.color[bound:]
        def optional(color: Color | None, bound: int | Index | str) -> str:
            if color is None:
                return ''
            return color[bound:]
        def conditional(flag: bool, bound: int | Index | str) -> str:
            color = Color.RED if flag else Color.BLUE
            return color[bound:]
        def main() -> str:
            rows = [literal('abcdef', Index()), attribute(Box(Color.RED), Index()),
                    optional(Color.RED, Index()), conditional(False, Index())]
            for bound in [1, Index(), 'bad']:
                try:
                    rows.append(literal('uvwxyz', bound))
                except TypeError:
                    rows.append('bad literal')
                try:
                    rows.append(attribute(Box(Color.BLUE), bound))
                except TypeError:
                    rows.append('bad attribute')
                try:
                    rows.append(optional(Color.RED, bound))
                except TypeError:
                    rows.append('bad optional')
                try:
                    rows.append(conditional(True, bound))
                except TypeError:
                    rows.append('bad conditional')
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("decoration, parameter", [
    ("staticmethod", ""), ("classmethod", "cls"), ("property", "self"),
])
def test_slice_callbacks_validate_reached_override_descriptors(decoration, parameter):
    with pytest.raises(LLVMUnsupported, match="__index__ requires an instance method returning int"):
        transpile_llvm(f'''
            class Base:
                def __index__(self) -> int:
                    return 1
            class Broken(Base):
                @{decoration}
                def __index__({parameter}) -> int:
                    return 2
            def selected(value: Base) -> str:
                return 'abc'[value:]
            def main() -> str:
                return selected(Broken())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_callback_allocation_failure_precedes_mutation_and_recovers(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Bound:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                temporary = [self.value]
                gc_collect()
                return temporary[0]
        def assign(values: list[str], replacement: list[str]) -> None:
            values[Bound(1):Bound(3):Bound(1)] = replacement
        def main() -> int:
            caught = 0
            for attempt in range(1, 40):
                values = ['a', 'b', 'c', 'd']
                alias = values
                replacement = ['new:' + str(i) for i in range(3)]
                succeeded = False
                arm(attempt)
                try:
                    assign(values, replacement)
                    succeeded = True
                except MemoryError:
                    arm(0)
                    caught += 1
                    assert values == ['a', 'b', 'c', 'd']
                finally:
                    arm(0)
                assert alias is values
                gc_collect()
                if succeeded:
                    assert values == ['a', 'new:0', 'new:1', 'new:2', 'd']
                    return 0 if caught else 1
                assign(values, replacement)
                gc_collect()
                assert values == ['a', 'new:0', 'new:1', 'new:2', 'd']
            return 2
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_invalid_range_slice_messages_match_required_python(optimize):
    # CPython3.14 uses the generic slice message here too. Keep the oracle
    # explicit: an older-version assumption previously invented a doc limitation.
    result = LLVM().assert_matches_python('''
        def messages(bound: object) -> str:
            rows: list[str] = []
            try:
                range(3)[bound:]
            except TypeError as error:
                rows.append(str(error))
            try:
                range(3)[:bound]
            except TypeError as error:
                rows.append(str(error))
            try:
                range(3)[::bound]
            except TypeError as error:
                rows.append(str(error))
            return '|'.join(rows)
        def main() -> str:
            return messages('x') + messages(1.5)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
