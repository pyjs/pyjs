import sys
from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT, NativeInferenceVisitor
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


def test_runtime_tuple_concat_keeps_analyzed_shape_and_operand_order():
    with analyze_source(dedent('''
        def main(left: tuple[int, ...], right: tuple[int, ...]) -> int:
            values = left + right
            return values[0]
    '''), environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        assert analysis.types == dedent('''
            def main(left: tuple__int__variadic, right: tuple__int__variadic) -> int:
                block entry:
                    $assignment3: tuple[int, ...] = left
                    $assignment4: tuple[int, ...] = right
                    values: tuple[int, ...] = $assignment3.[tuple__int__variadic]__add__($assignment4)
                    return values.[tuple__int__variadic]__getitem__(0)
        ''').strip()


@pytest.mark.parametrize("operand", ["receiver", "argument"])
def test_nested_explicit_concat_analysis_is_linear(operand):
    depth = 8
    expression = "value"
    for _ in range(depth):
        expression = f"{expression}.__add__(value)" if operand == "receiver" else f"value.__add__({expression})"
    source = f"def main() -> int:\n    value = tuple([1])\n    return len({expression})\n"
    visits = 0
    hook = NativeInferenceVisitor.analyze_tuple_concat.__code__

    def profile(frame, event, argument):
        nonlocal visits
        if event == "call" and frame.f_code is hook:
            visits += 1

    # Count actual analysis, without replacing/stubbing it or asserting wall
    # time. Modest depth catches exponential revisits without hanging CI.
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        with analyze_source(source, environment=NATIVE_ENVIRONMENT, wrap=False):
            pass
    finally:
        sys.setprofile(previous)
    # Receiver discovery may analyze a call before binding its enclosing
    # method, but nested calls must not recursively reanalyze their operands.
    assert depth <= visits <= 2 * depth
    result = LLVM().assert_matches_python(source, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    '(make("x", index) + make("y", 1)).__add__(make("z", 2))',
    'make("x", index).__add__(make("y", 1) + make("z", 2))',
])
def test_explicit_concat_reanalyzes_operands_for_each_finally_path(optimize, expression):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        events: list[str] = []
        def make(tag: str, count: int) -> tuple[int, ...]:
            events.append(tag)
            gc_collect()
            return tuple(range(count))

        def collect(stop: int) -> int:
            total = 0
            for index in range(3):
                try:
                    if index == stop:
                        break
                finally:
                    total += len({expression})
            return total

        def main() -> str:
            gc_set_threshold(1)
            result: list[int] = []
            for stop in (0, 1, 4):
                result.append(collect(stop))
            return repr((result, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "value.__add__(value)", "value.__add__(fixed)", "fixed.__add__(value)",
])
@pytest.mark.parametrize("other,guard,replacement", [
    ("None", "value is None", "None"),
    ("str", "isinstance(value, str)", '"changed"'),
])
def test_explicit_concat_does_not_cache_narrowing_across_flow_retries(expression, other, guard, replacement):
    source = f'''def consume(value: tuple[int, ...] | {other}) -> int:
    if {guard}:
        return 0
    fixed = tuple([7])
    for index in range(3):
        result = {expression}
        value = {replacement}
    return len(result)
def main() -> int:
    return consume(tuple([1, 2]))
'''
    # A loop retry widens value again. Retaining the first pass's narrowed
    # operand would incorrectly compile this and rely on a runtime trap.
    with pytest.raises(CompilationError, match="not defined on every member|expects tuple|requires another tuple") as caught:
        transpile_llvm(source)
    assert caught.value.lineno == 6


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["left + right", "concat(left, right)", "iconcat(left, right)"])
def test_runtime_tuple_concatenation_preserves_values_and_empty_aliases(optimize, expression):
    result = LLVM().assert_matches_python(f"""
        from operator import concat, iconcat
        def combine(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
            return {expression}

        def main() -> str:
            rows: list[str] = []
            for length in (0, 1, 3):
                left = tuple(range(length))
                right = tuple(range(4, 6))
                joined = combine(left, right)
                reverse = combine(right, left)
                rows.append(str((joined, reverse, joined is right,
                                 reverse is right, left + (9, 10), (9, 10) + left,
                                 (left + ()) is left, (() + left) is left)))
            return str(rows)
    """, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_concatenated_tuples_retain_objects_and_hash_cache_shortcuts(optimize):
    result = LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.calls = 0

            def __hash__(self) -> int:
                self.calls += 1
                gc_collect()
                return self.value

        def combine(left: tuple[Key, ...], right: tuple[Key, ...]) -> tuple[Key, ...]:
            return left + right

        def build() -> tuple[Key, ...]:
            return combine(tuple([Key(1), Key(2)]), (Key(3), Key(4)))

        def main() -> str:
            gc_set_threshold(1)
            values = build()
            first = hash(values)
            empty: tuple[Key, ...] = ()
            left = combine(empty, values)
            right = combine(values, empty)
            same = hash(left) == first and hash(right) == first
            before = values[0].calls
            doubled = values + values
            hash(doubled)
            gc_collect()
            return str((left is values, right is values, same, before,
                        values[0].calls, values[3].calls,
                        [key.value for key in doubled], doubled[0] is doubled[4]))
    """, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_runtime_tuple_concatenation_preserves_portable_item_representation():
    result = LLVM().assert_matches_python("""
        from pyjs import int8, int64

        def main() -> str:
            small = tuple([int8(120)]) + (int8(10),)
            wide = (int64(9007199254740993),) + tuple([int64(1)])
            return str((small[0] + small[1], wide[0] + wide[1]))
    """, sanitizers=("address", "undefined"))
    assert not result.native.stderr



def test_runtime_tuple_concatenation_roots_temporaries_during_operand_evaluation():
    result = LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        EVENTS: list[str] = []

        class Box:
            def __init__(self, name: str):
                self.name = name

        def make(name: str) -> tuple[Box, ...]:
            EVENTS.append(name)
            gc_collect()
            return tuple([Box(name)])

        def main() -> str:
            gc_set_threshold(1)
            values = make("left") + make("right")
            gc_collect()
            return str((EVENTS, values[0].name, values[1].name))
    """, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_concatenated_borrowed_tuples_survive_later_library_calls(tmp_path):
    library = LLVM().compile_library("""
        from pyjs.native import gc_collect, gc_set_threshold

        SAVED: list[tuple[str, ...]] = []

        def render(left: tuple[str, ...], right: tuple[str, ...]) -> str:
            gc_set_threshold(1)
            SAVED.append(left + right)
            gc_collect()
            return str(SAVED)
    """, tmp_path, entry_point="render")
    try:
        assert library.render(("one",), ("two",)) == "[('one', 'two')]"
        assert library.render(("three",), ()) == "[('one', 'two'), ('three',)]"
        assert library.render((), ("four",)) == (
            "[('one', 'two'), ('three',), ('four',)]"
        )
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_equivalent_union_tuple_fields_iterate_and_concatenate(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        class First:
            def __init__(self): self.item = Box(3)
            @property
            def value(self) -> Box: return self.item
        class Second:
            def __init__(self): self.item = "second"
            @property
            def value(self) -> str: return self.item
        def render(source: First | Second) -> str:
            fields = (source.item, source.item)
            properties = (source.value, source.value)
            values: tuple[Box | str, ...] = fields
            joined = values + properties
            view: tuple[Box | str, ...] = (source.value, source.value)
            assert fields == view and view == fields
            assert not (fields != view or view != fields)
            for length in (0, 1, 2, 3):
                items: list[Box | str] = []
                for index in range(length):
                    items.append(source.item)
                sized = tuple(items)
                assert (fields == sized) == (length == 2)
                assert (sized == fields) == (length == 2)
                assert (fields != sized) == (length != 2)
                assert (sized != fields) == (length != 2)
            gc_collect()
            rows: list[str] = []
            for pair in (fields, properties):
                for item in pair:
                    rows.append(str(item.value) if isinstance(item, Box) else item)
            for item in joined:
                rows.append(str(item.value) if isinstance(item, Box) else item)
            return "|".join(rows)
        def main() -> str:
            gc_set_threshold(1)
            return render(First()) + ";" + render(Second())
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("left,right", [("1", '"two"'), ("True", "1"), ("1", "1.5")])
def test_runtime_tuple_concatenation_rejects_incompatible_payloads(left, right):
    with pytest.raises(LLVMUnsupported, match="tuple views require matching"):
        transpile_llvm(f'''
def main() -> int:
    return len(tuple([{left}]) + tuple([{right}]))
''')


def test_runtime_tuple_concatenation_rejects_mixed_portable_widths():
    with pytest.raises(CompilationError, match="representation"):
        transpile_llvm('''
from pyjs import int8, int16
def main() -> int:
    return len(tuple([int8(1)]) + tuple([int16(2)]))
''')


@pytest.mark.parametrize("expression,diagnostic", [
    ("(1,).__add__()", "missing"),
    ("(1,).__add__((2,), (3,))", "too many"),
    ("(1,).__add__(other=(2,))", "positional-only"),
    ("(1,).__add__([2])", "expects tuple"),
    ("tuple.__add__((1,), (2,))", "unspecialized generic"),
    ('(1,).__add__(*(("two",),))', "explicit positional argument"),
    ('(1,).__add__(**{})', "missing"),
])
def test_tuple_add_reports_invalid_call_shapes(expression, diagnostic):
    with pytest.raises(CompilationError, match=diagnostic):
        transpile_llvm(f"def main() -> int:\n    return len({expression})\n")


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_tuple_concat_allocation_failure_leaves_inputs_and_retry_intact(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        class Box:
            def __init__(self, value: int): self.value = value
        def main() -> int:
            gc_set_threshold(1)
            left = tuple([Box(2)])
            right = tuple([Box(3), Box(4)])
            failures = 0
            exhausted = False
            for stage in range(1, 100):
                try:
                    arm(stage)
                    joined = left + right
                    exhausted = remaining() > 0
                    arm(0)
                    assert joined[0] is left[0] and joined[2] is right[1]
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert left[0].value == 2 and right[0].value == 3
                retry = left + right
                assert [box.value for box in retry] == [2, 3, 4]
                if exhausted: break
            assert failures > 0 and exhausted
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
