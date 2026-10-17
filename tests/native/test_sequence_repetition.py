import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    LITERAL_SEQUENCE_REFLECTION_CONTRACT,
    SEQUENCE_REFLECTION_CONTRACT,
)
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("contract", [SEQUENCE_REFLECTION_CONTRACT, LITERAL_SEQUENCE_REFLECTION_CONTRACT])
def test_shared_sequence_reflection_contract(contract):
    result = LLVM().assert_matches_python(contract.source, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_selected_numeric_method_does_not_reach_unused_index_body():
    result = LLVM().assert_matches_python('''
        class Count:
            def __mul__(self, value: str) -> int:
                return 21
            def __rmul__(self, value: str) -> int:
                return 21
            def __index__(self) -> int:
                return len(0)
        def main() -> int:
            return 'x' * Count() + Count() * 'x'
    ''')
    assert result.native.returncode == 42
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_strenum_repetition_preserves_numeric_priority_and_nominal_operand(optimize):
    result = LLVM().assert_matches_python('''
        from enum import StrEnum
        from pyjs.native import gc_collect, gc_set_threshold
        class Text(StrEnum):
            X = 'x'
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return 2
        class Count(Index):
            def __mul__(self, value: Text) -> str:
                gc_collect()
                return 'forward:' + value.name
            def __rmul__(self, value: Text) -> str:
                gc_collect()
                return 'reflected:' + value.name
        def run(count: Index) -> str:
            return repr((Text.X * count, count * Text.X))
        def main() -> str:
            gc_set_threshold(1)
            return repr((Text.X * Count(), Count() * Text.X,
                         run(Index()), run(Count()), Text.X.__mul__(Count())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Literal['x']", "Literal['x', 'y']",
    "Annotated[Literal['x'], 'label']", "Text"])
def test_literal_string_repetition_preserves_numeric_priority(optimize, annotation):
    result = LLVM().assert_matches_python('''
        from typing import Annotated, Literal
        from pyjs.native import gc_collect, gc_set_threshold
        type Text = Literal['x', 'y']
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return 2
        class Count(Index):
            def __mul__(self, value: str) -> str:
                gc_collect()
                return 'forward:' + value
            def __rmul__(self, value: str) -> str:
                gc_collect()
                return 'reflected:' + value
        def direct(text: ANNOTATION) -> str:
            return text * Count()
        def dynamic(text: ANNOTATION, count: Index) -> str:
            return repr((text * count, count * text, text.__mul__(count)))
        def main() -> str:
            gc_set_threshold(1)
            return direct('x') + dynamic('x', Index()) + dynamic('x', Count())
    '''.replace('ANNOTATION', annotation), optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("count", ["Count()", "Child()", "Disabled()"])
def test_inplace_reflection_does_not_reach_unused_index_body(optimize, count):
    result = LLVM().assert_matches_python('''
        class Count:
            def __rmul__(self, other: list[int]) -> list[int]:
                return [42]
            def __index__(self) -> int:
                return len(0)
        class Child(Count):
            pass
        class Disabled(Count):
            __rmul__ = None
        def main() -> str:
            values = [1]
            try:
                values *= COUNT
            except TypeError:
                return 'TypeError'
            return repr(values)
    '''.replace('COUNT', count), optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_checked_sequence_repetition_and_explicit_dunders(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, count: int, events: list[str]):
                self.count, self.events = count, events
            def __index__(self) -> int:
                self.events.append('index')
                gc_collect()
                return self.count
        class Previous(Index):
            def __index__(self) -> int:
                return super().__index__() - 1
        def run(count: int) -> str:
            events: list[str] = []
            index = Previous(count + 1, events)
            values = [1, 2]
            alias = values
            values *= index
            result = repr(('x' * index, index * 'x', b'y' * index, index * b'y',
                           [3] * index, index * [3], (4, 5) * index, index * (4, 5),
                           values, alias, alias is values))
            result += repr(('z'.__mul__(index), b'z'.__rmul__(index),
                            [6].__mul__(index), (6,).__rmul__(index),
                            list.__mul__([6], index), tuple.__rmul__((6,), index)))
            return result + ':' + str(len(events))
        def main() -> str:
            gc_set_threshold(1)
            return '|'.join([run(-2), run(0), run(1), run(3)])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_multiplication_precedes_sequence_repetition(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return 2
        class Override(Index):
            def __mul__(self, value: str) -> str:
                gc_collect()
                return 'forward:' + value
            def __rmul__(self, value: str) -> str:
                gc_collect()
                return 'reflected:' + value
        def run(index: Index) -> str:
            return repr(('x' * index, index * 'x', 'x'.__mul__(index), 'x'.__rmul__(index)))
        def main() -> str:
            gc_set_threshold(1)
            return run(Index()) + run(Override()) + str('z' * Override())
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_conditional_subscript_result_mismatch_keeps_annotation_location():
    # Dynamic subscripts support either arm now; an int-only return contract
    # still cannot accept the possible list slice result.
    with pytest.raises(CompilationError, match=r"Function returns int \| list\[int\], not int") as caught:
        transpile_llvm('''
def choose(index: object, flag: bool) -> int:
    return [1, 2][index if flag else 0]
def main() -> int:
    return choose(0, True)
''')
    assert caught.value.lineno == 2


@pytest.mark.parametrize("expression", ["'x'.__mul__(times=2)", "b'x'.__rmul__(count=2)",
    "[1].__mul__(count=2)", "[1].__imul__(count=2)", "(1,).__rmul__(times=2)"])
def test_sequence_repetition_dunders_reject_keyword_counts(expression):
    with pytest.raises(CompilationError, match="positional.only"):
        transpile_llvm(f"def main():\n    return {expression}\n")


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("count_annotation", ["Index", "object"])
def test_repetition_captures_operands_before_callbacks_and_preserves_aliases(optimize, count_annotation):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, values: list[str], events: list[str], action: int):
                self.values, self.events, self.action = values, events, action
            def __index__(self) -> int:
                self.events.append('index')
                if self.action == 1:
                    self.values.clear()
                if self.action == 2:
                    self.values.extend(['extra'] * 100)
                gc_collect()
                if self.action == 3:
                    raise ValueError('index error')
                return 2
        class Reflected(Index):
            def __rmul__(self, other: list[str]) -> list[str]:
                self.events.append('reflect')
                other.append('changed')
                gc_collect()
                if self.action == 3:
                    raise ValueError('reflection error')
                return ['replacement']
        def left(pool: list[list[str]], events: list[str]) -> list[str]:
            events.append('left')
            return pool[0]
        def right(pool: list[list[str]], events: list[str], index: Index) -> COUNT_ANNOTATION:
            events.append('right')
            pool.clear()
            gc_collect()
            return index
        def run(index: Index, reverse: bool, inplace: bool) -> str:
            pool = [index.values]
            alias = index.values
            result = alias
            try:
                if inplace:
                    result *= right(pool, index.events, index)
                elif reverse:
                    result = right(pool, index.events, index) * left([alias], index.events)
                else:
                    result = left(pool, index.events) * right(pool, index.events, index)
                answer = 'ok'
            except ValueError as error:
                answer = str(error)
            return repr((answer, result, alias, result is alias, index.events))
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for action in range(4):
                rows.append(run(Index(['a'], [], action), False, False))
                rows.append(run(Index(['a'], [], action), True, False))
                rows.append(run(Index(['a'], [], action), False, True))
                rows.append(run(Reflected(['a'], [], action), False, False))
                rows.append(run(Reflected(['a'], [], action), False, True))
            return '|'.join(rows)
    '''.replace('COUNT_ANNOTATION', count_annotation), optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_explicit_repetition_and_invalid_counts(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return 2
            def __rmul__(self, value: str) -> str:
                return 'must not reflect'
        class Count(IntEnum):
            TWO = 2
        def direct(count: object) -> str:
            try:
                return repr(('x'.__mul__(count), b'x'.__rmul__(count),
                             [1].__mul__(count), (1,).__rmul__(count)))
            except TypeError:
                return 'TypeError'
        def optional(count: int | None) -> str:
            try:
                return 'x' * count
            except TypeError:
                return 'TypeError'
        def main() -> str:
            gc_set_threshold(1)
            return repr((direct(Index()), direct(2), direct(True), direct(None),
                         direct(1.5), direct('x'), direct(slice(1)), optional(2),
                         optional(None), 'x' * int8(2), Count.TWO * b'x'))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_disabled_reflection_and_explicit_inplace_dunder():
    result = LLVM().assert_matches_python('''
        class Index:
            def __index__(self) -> int:
                return 2
        class Disabled(Index):
            __rmul__ = None
        class Reflected(Index):
            def __rmul__(self, other: list[int]) -> list[int]:
                return [99]
        def run(index: Index) -> str:
            values = [7]
            alias = values
            try:
                values *= index
                answer = 'ok'
            except TypeError:
                answer = 'TypeError'
            direct = [8]
            direct.__imul__(index)
            return repr((answer, values, alias, direct))
        def main() -> str:
            return run(Index()) + run(Disabled()) + run(Reflected())
    ''', sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("annotation", ["object", "Index | int", "Index | None"])
@pytest.mark.parametrize("expression", ["'x' * count", "count * 'x'"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_repetition_preserves_numeric_reflection(annotation, expression, optimize):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
class Index:
    def __index__(self) -> int:
        gc_collect()
        return 2
class Override(Index):
    def __rmul__(self, value: str) -> str:
        gc_collect()
        return 'reflected'
    def __mul__(self, value: str) -> str:
        gc_collect()
        return 'forward'
def repeat(count: {annotation}) -> str:
    try:
        return {expression}
    except TypeError:
        return 'TypeError'
def main() -> str:
    gc_set_threshold(1)
    return repeat(Override()) + repeat(Index()) + repeat({'3' if annotation == 'Index | int' else 'None'})
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Index", "object"])
def test_repetition_allocation_failures_leave_list_usable(tmp_path, optimize, annotation):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Index:
            def __index__(self) -> int:
                temporary = [3]
                gc_collect()
                return temporary[0]
        def main() -> int:
            values = [7]
            alias = values
            index: ANNOTATION = Index()
            caught = 0
            for attempt in range(1, 50):
                succeeded = False
                arm(attempt)
                try:
                    values *= index
                    succeeded = True
                except MemoryError:
                    caught += 1
                finally:
                    arm(0)
                gc_collect()
                assert values is alias
                if succeeded:
                    assert values == [7, 7, 7]
                    return 0 if caught else 1
                assert values == [7]
                assert values * index == [7, 7, 7]
            return 2
    '''.replace('ANNOTATION', annotation))
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("method, annotation, body, message", [
    ("__rmul__", "str", "return 'wrong'", "operand must preserve"),
    ("__rmul__", "list[int]", "return 'wrong'", "result must preserve"),
    ("__mul__", "str", "return 'wrong'", "operand must preserve"),
])
@pytest.mark.parametrize("count_annotation", ["Index", "object", "Index | int", "Index | None"])
def test_runtime_repeat_overrides_preserve_argument_and_result_layouts(
        method, annotation, body, message, count_annotation):
    expression = "[1] * index" if method == "__rmul__" else "index * [1]"
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
class Index:
    def __index__(self) -> int:
        return 2
class Override(Index):
    def {method}(self, value: {annotation}) -> str:
        {body}
def repeat(index: {count_annotation}) -> list[int]:
    return {expression}
def main() -> list[int]:
    return repeat(Override())
''')
