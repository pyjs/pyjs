import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import COMPREHENSION_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_lambda_comprehension_result_survives_its_frame(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def make(values: list[int]) -> list[int]:
            transform: Callable[[list[int]], list[int]] = lambda items: [value + 1 for value in items]
            return transform(values)
        def main() -> str:
            gc_set_threshold(1)
            first = make([1, 2])
            empty = make([])
            gc_collect()
            second = make([3])
            gc_collect()
            return repr((first, empty, second))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_shared_comprehension_contract():
    result = LLVM().assert_matches_python(COMPREHENSION_CONTRACT.source)
    assert result.native.returncode == 0, COMPREHENSION_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_eager_comprehensions_have_isolated_scope_and_order(optimize):
    LLVM().assert_matches_python('''
        def main() -> int:
            values = [1, 2, 3]
            rows = [left * 10 + right for left in values if left > 1 for right in range(left) if right != 1]
            table = {value: value * 2 for value in values if value != 2}
            unique = {value % 2 for value in values}
            values = [value + 1 for value in values]
            assert len(rows) == 3 and rows[0] == 20 and rows[1] == 30 and rows[2] == 32
            assert len(table) == 2 and table[3] == 6 and 2 not in table
            assert len(unique) == 2
            return values[0] + values[2]
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_comprehensions_conditionals_destructuring_and_effect_order(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, values: list[int]):
                self.values = values

        def mark(events: list[int], value: int) -> int:
            events.append(value)
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            rows = [[mark(events, a * 10 + b) if b else mark(events, a)
                     for b in range(2)] for a in [1, 2]]
            assert rows == [[1, 11], [2, 21]]
            assert events == [1, 11, 2, 21]
            events.clear()
            table = {mark(events, a): mark(events, a + 10) for a in [1, 1, 2]}
            assert events == [1, 11, 1, 11, 2, 12]
            assert table == {1: 11, 2: 12}
            pairs = [(1, (2, 3)), (4, (5, 6))]
            unpacked = [a + b + c for a, (b, c) in pairs]
            value = [1, 2]
            value = [value * 2 for value in value]
            box = Box([7, 8])
            copied = [item for item in box.values]
            literals = [item for item in ["one", "two"] if item]
            assert [item for item in range(0)] == []
            assert unpacked == [6, 15] and value == [2, 4]
            assert copied == [7, 8] and literals == ["one", "two"]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_comprehension_contextual_callables_and_represented_items(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs import int8
        from pyjs.native import gc_collect

        def make() -> list[Callable[[int8], int8]]:
            return [lambda value: value + offset for offset in [int8(1), int8(2)]]

        def mapping() -> dict[str, Callable[[int8], int8]]:
            return {key: lambda value: value + int8(1) for key in ["add"]}

        def main() -> int:
            callbacks = make()
            named = mapping()
            values = [value + int8(1) for value in [int8(126), int8(127)]]
            gc_collect()
            assert callbacks[0](int8(127)) == int8(-127)
            assert named["add"](int8(127)) == int8(-128)
            assert values == [int8(127), int8(-128)]
            return int(callbacks[1](int8(2)))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_comprehension_closures_share_cells_per_evaluation(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def identity(callback: Callable[[], int]) -> Callable[[], int]:
            return callback

        def make(offset: int) -> list[Callable[[], int]]:
            return [identity(lambda: value + offset) for value in range(3)]

        def main() -> int:
            gc_set_threshold(1)
            value = 100
            first = make(10)
            second = make(20)
            gc_collect()
            assert value == 100
            assert first[0]() == 12 and first[2]() == 12
            return second[0]()
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_failed_comprehension_preserves_assignment_and_callback_effects(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def record(events: list[int], value: int) -> str:
            events.append(value)
            gc_collect()
            if value == 2:
                raise ValueError("two")
            return str(value)

        def main() -> str:
            gc_set_threshold(1)
            result = ["original"]
            events: list[int] = []
            try:
                result = [record(events, value) for value in [1, 2, 3]]
            except ValueError as error:
                assert str(error) == "two"
            else:
                assert False
            gc_collect()
            assert result == ["original"] and events == [1, 2]
            return ":".join([record(events, value) for value in [4, 5]])
    ''', optimize=optimize)


def test_comprehensions_build_filtered_dom_rows_with_escaping():
    LLVM().assert_matches_python('''
        from pyjs.web.domx import div, span
        from pyjs.web.ssr import render_html
        from pyjs.native import gc_collect

        def main() -> str:
            labels = ["<first>", "", "second & third"]
            rows = [div({"data-row": str(index)}, span(label))
                    for index, label in enumerate(labels) if label]
            gc_collect()
            return render_html(div(*rows))
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "[x for x in [1] if later for later in [2]]",
    "{x for x in [1] if later for later in [2]}",
    "{x: later for x in [1] if later for later in [2]}",
    "[x + y for x in [1] for y in later for later in [[2]]]",
    "[x for x in [1] if later for _, (later, _) in [(0, (2, 3))]]",
])
def test_comprehension_forward_locals_raise_instead_of_capturing_outer_values(expression, optimize):
    LLVM().assert_matches_python(f'''
        def main() -> int:
            later = "an enclosing value of a different type"
            try:
                values = {expression}
            except UnboundLocalError:
                return 42
            return len(values)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_comprehension_forward_cells_and_short_circuits_follow_runtime_binding(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect

        def save(callbacks: list[Callable[[], int]], callback: Callable[[], int]) -> bool:
            callbacks.append(callback)
            gc_collect()
            return True

        def invoke(callback: Callable[[], int]) -> bool:
            return callback() > 0

        def main() -> int:
            callbacks: list[Callable[[], int]] = []
            values = [x for x in [1] if save(callbacks, lambda: later) for later in [2, 3]]
            assert values == [1, 1] and callbacks[0]() == 3
            try:
                values = [x for x in [1] if invoke(lambda: pending) for pending in [2]]
            except UnboundLocalError:
                assert False
            except NameError:
                pass
            else:
                assert False
            try:
                values = [x for x in [1] if missing for missing in [2]]
            except UnboundLocalError:
                pass
            else:
                assert False
            empty: list[int] = []
            assert [x for x in empty if later for later in [2]] == []
            assert [x for x in [1] if False for y in later for later in [[2]]] == []
            # The second outer iteration sees the local left by the first.
            values = [x for x in [0, 1] if x == 0 or later != 0 for later in [2]]
            assert values == [0, 1]
            gc_collect()
            return callbacks[0]()
    ''', optimize=optimize)
