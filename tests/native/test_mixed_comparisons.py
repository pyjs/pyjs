import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("second", ["Key(mode, events)", "True"])
def test_tuple_prefix_callbacks_precede_length_comparison(tmp_path, optimize, second):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, mode: int, events: list[int]):
                self.mode = mode
                self.events = events

            def __eq__(self, other: object) -> bool:
                self.events.append(self.mode)
                gc_collect()
                if self.mode == 2:
                    raise ValueError("prefix compared")
                return self.mode == 1

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            results: list[str] = []
            for mode in range(3):
                fixed = (Key(mode, events), {second})
                for length in range(4):
                    runtime = tuple([1 for _ in range(length)])
                    for operation in range(4):
                        try:
                            if operation == 0:
                                matched = fixed == runtime
                            elif operation == 1:
                                matched = runtime == fixed
                            elif operation == 2:
                                matched = fixed != runtime
                            else:
                                matched = runtime != fixed
                            results.append(str(matched))
                        except ValueError as error:
                            results.append(str(error))
                short = (1,)
                for operation in range(4):
                    try:
                        if operation == 0:
                            matched = fixed == short
                        elif operation == 1:
                            matched = short != fixed
                        elif operation == 2:
                            matched = (fixed, 3) == (short, 3)
                        else:
                            matched = [short] != [fixed]
                        results.append(str(matched))
                    except ValueError as error:
                        results.append(str(error))
                # Unlike tuples, unequal lists do not visit their prefix.
                results.append(str([fixed[0]] == []))
            return str((results, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("left_format, right_format, message", [
    ("int8", "float32", "different fixed-width numeric types cannot be compared implicitly"),
    ("int8", "int16", "different fixed-width numeric types cannot be compared implicitly"),
    ("float32", "float64", "different fixed-width numeric types cannot be compared implicitly"),
    ("int64", "float", "int64 and float comparisons cannot be mixed implicitly"),
])
@pytest.mark.parametrize("operator", ["==", "!="])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_tuple_comparison_preserves_paired_numeric_formats(left_format, right_format, message, operator, reverse, nested):
    left, right = ("runtime", "fixed") if reverse else ("fixed", "runtime")
    if nested:
        left, right = f"[{left}]", f"[{right}]"
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            from pyjs import int8, int16, int64, float32, float64
            def main() -> bool:
                fixed = ({left_format}(1), {left_format}(2))
                runtime = tuple([{right_format}(1), {right_format}(2)])
                return {left} {operator} {right}
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_comparison_keeps_matching_and_ordinary_numeric_controls(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        def main() -> str:
            fixed = (int8(1), int8(2))
            runtime = tuple([int8(1), int8(2)])
            plain = tuple([1, 2])
            floating = tuple([float32(1), float32(2)])
            ordinary = (1.0, 2.0)
            return str((fixed == runtime, runtime == fixed, fixed == plain,
                        plain == fixed, floating == ordinary, ordinary == floating,
                        floating == plain, plain == floating,
                        [fixed] != [runtime]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("stored, query, message", [
    ("int8", "float32", "different fixed-width numeric types cannot be compared implicitly"),
    ("int8", "int16", "different fixed-width numeric types cannot be compared implicitly"),
    ("float32", "float64", "different fixed-width numeric types cannot be compared implicitly"),
    ("int64", "float", "int64 and float comparisons cannot be mixed implicitly"),
])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("operation", ["count", "index"])
def test_tuple_search_validates_item_query_numeric_formats(stored, query, message, reverse, nested, operation):
    source, needle = ("runtime", "fixed") if reverse else ("fixed", "runtime")
    if nested:
        source, needle = f"[{source}]", f"[{needle}]"
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            from pyjs import int8, int16, int64, float32, float64
            def main() -> int:
                fixed = ({stored}(1), {stored}(2))
                runtime = tuple([{query}(1), {query}(2)])
                return ({source},).{operation}({needle})
        ''')


@pytest.mark.parametrize("operation", ["count", "index"])
def test_tuple_search_does_not_erase_represented_callback_arguments(operation):
    with pytest.raises(LLVMUnsupported, match="object comparison callbacks require ordinary item representations"):
        transpile_llvm(f'''
            from pyjs import int8
            class Key:
                def __eq__(self, other: object) -> bool:
                    return isinstance(other, int) and other + 125 == -128
            def main() -> int:
                source = ((Key(),),)
                return source.{operation}(tuple([int8(3)]))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_sequence_search_retains_matching_formats_and_independent_slots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        class Key:
            def __eq__(self, other: object) -> bool:
                return isinstance(other, Key)
        def main() -> str:
            fixed = (int8(1), int8(2))
            runtime = tuple([int8(1), int8(2)])
            floating = tuple([float32(1), float32(2)])
            keys = ((Key(), int8(3)),)
            values = {"a": (1, 2)}
            plain = tuple([1, 2])
            return repr(((fixed,).count(runtime), (runtime,).count(fixed),
                         (fixed,).count(tuple([1, 2])),
                         ((1.0, 2.0),).count(floating),
                         ((float32(1),), "unrelated").count(tuple([1])),
                         keys.count((Key(), 3)), plain in values.values(),
                         [runtime].index(runtime), [fixed].count(fixed),
                         int8(3) in {1: int8(3)}.values(),
                         (1, int8(3)) in {1: int8(3)}.items()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_heterogeneous_equality_boxes_object_parameters(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass
        from pyjs.native import gc_collect, gc_set_threshold

        class Match:
            def __init__(self, expected: str, events: list[str]):
                self.expected = expected
                self.events = events

            def __eq__(self, other: object) -> bool:
                gc_collect()
                actual = repr(other)
                self.events.append(actual)
                if self.expected == "error":
                    raise ValueError("comparison")
                return actual == self.expected

        @dataclass
        class Record:
            value: int

        class Plain:
            pass

        class BoolMatch:
            def __eq__(self, other: bool) -> bool:
                return other

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            answers = [
                [Match("42", events)] == [42],
                [42] == [Match("42", events)],
                [(Match("2.5", events),)] == [(2.5,)],
                [Match("True", events)] == [True],
                [Match("None", events)] == [None],
                [None] == [Match("None", events)],
                [Match("'café'", events)] == ["café"],
                [Match("b'bytes'", events)] == [b"bytes"],
                [Match("[1, 2]", events)] == [[1, 2]],
                [(1, "two")] == [Match("(1, 'two')", events)],
                [{"one": 1}] == [Match("{'one': 1}", events)],
                {"key": Match("42", events)} == {"key": 42},
                {"key": "café"} == {"key": Match("'café'", events)},
                [Match("no", events)] != [{2}],
                [Record(1)] != [1], ["a"] != [Record(1)],
                [Plain()] != [1], [None] != [Plain()],
                [BoolMatch()] == [True], [False] == [BoolMatch()],
            ]
            try:
                [Match("error", events)] == [[3]]
            except ValueError as error:
                events.append(str(error))
            gc_collect()
            answers.append([Match("42", events)] == [42])
            return str((answers, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", ["[Box()] == [1]", "[1] == [Box()]"])
def test_callback_argument_rejects_incompatible_pointer_storage(expression):
    with pytest.raises(LLVMUnsupported, match="compatible typed argument and bool result"):
        transpile_llvm(f'''
            class Box:
                def __eq__(self, other: str) -> bool:
                    return len(other) > 0

            def main() -> bool:
                return {expression}
        ''')


def test_narrow_callback_keeps_explicit_numeric_conversion_boundary():
    # As for an ordinary native call, an int annotation does not convert a
    # boolean argument into an integer. Use object to preserve its type, or
    # convert explicitly before storing the compared collection member.
    with pytest.raises(LLVMUnsupported, match="use an explicit numeric conversion"):
        transpile_llvm('''
            class Box:
                def __eq__(self, other: int) -> bool:
                    return other == 1

            def main() -> bool:
                return [Box()] == [True]
        ''')


@pytest.mark.parametrize("expression", [
    "accept(3)", "Box().accept(3)", "Box() == 3", "3 == Box()",
    "[Box()] == [3]", "[True] == [Box()]", "{'x': Box()} == {'x': 3}",
    "forward('text')",
])
def test_union_parameters_do_not_implicitly_promote_numeric_tags(expression):
    with pytest.raises(LLVMUnsupported, match="explicit numeric conversion"):
        transpile_llvm(f'''
            def accept(other: float | str) -> bool:
                return other == 3

            def forward(value: int | str) -> bool:
                return accept(value)

            class Box:
                def accept(self, other: float | str) -> bool:
                    return other == 3
                def __eq__(self, other: float | str) -> bool:
                    return other == 3

            def main() -> bool:
                return {expression}
        ''')


@pytest.mark.parametrize("receiver", ["[1]", "(1,)", "{1: 2}"])
@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
def test_explicit_builtin_dunder_does_not_invoke_reflected_callback(receiver, method):
    with pytest.raises(LLVMUnsupported, match="explicit builtin comparison dunders may return NotImplemented"):
        transpile_llvm(f'''
            class Box:
                def __eq__(self, other: object) -> bool:
                    return True

            def main() -> str:
                return str({receiver}.{method}(Box()))
        ''')


@pytest.mark.parametrize("receiver", ["[1]", "(1,)", "{1: 2}"])
@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
def test_explicit_builtin_dunder_checks_union_before_dispatch(receiver, method):
    with pytest.raises(LLVMUnsupported, match="explicit builtin comparison dunders may return NotImplemented"):
        transpile_llvm(f'''
            class Box:
                def __eq__(self, other: object) -> bool:
                    return True
                def __ne__(self, other: object) -> bool:
                    return False

            def compare(value: Box | int) -> str:
                return str({receiver}.{method}(value))

            def main() -> str:
                box = Box()
                box.__eq__(1)
                box.__ne__(1)
                return compare(box) + compare(1)
        ''')


@pytest.mark.parametrize("receiver, other", [
    ("[1]", "'hello'"), ("[1]", "(1,)"), ("(1,)", "[1]"),
    ("{1: 2}", "None"), ("{1}", "[1]"), ("frozenset([1])", "1"),
])
@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
def test_explicit_collection_dunder_rejects_unlike_builtin(receiver, other, method):
    with pytest.raises(LLVMUnsupported, match="explicit .*comparison.*NotImplemented"):
        transpile_llvm(f'''
            def main() -> str:
                return str({receiver}.{method}({other}))
        ''')


@pytest.mark.parametrize("expression", ["boxes == values", "values != boxes", "boxes.__eq__(values)"])
@pytest.mark.parametrize("boxes, annotation, value", [
    ("[Box()]", "list[int8]", "[int8(3)]"),
    ("(Box(),)", "tuple[int8]", "(int8(3),)"),
    ("{'x': Box()}", "dict[str, int8]", "{'x': int8(3)}"),
    ("[[Box()]]", "list[list[int8]]", "[[int8(3)]]"),
    ("[Box()]", "list[list[int8]]", "[[int8(3)]]"),
    ("[Box()]", "list[float32]", "[float32(3.0)]"),
    ("(Box(), int8(3))", "tuple[int8, Box]", "(int8(3), Box())"),
    ("tuple([Box(), Box()])", "tuple[int8, int8]", "(int8(3), int8(3))"),
    ("(Box(), Box())", "tuple[int8, ...]", "tuple([int8(3), int8(3)])"),
])
def test_mixed_callbacks_do_not_erase_item_representations(expression, boxes, annotation, value):
    with pytest.raises(LLVMUnsupported, match="object comparison callbacks require ordinary item representations"):
        transpile_llvm(f'''
            from pyjs import int8, float32

            class Box:
                def __eq__(self, other: object) -> bool:
                    if isinstance(other, int):
                        return other + 125 == -128
                    return False

            def main() -> str:
                boxes = {boxes}
                values: {annotation} = {value}
                return str({expression})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_ordinary_numeric_callback_and_explicit_collection_controls(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8

        class Box:
            def __eq__(self, other: object) -> bool:
                if isinstance(other, int):
                    return other + 125 == 128
                return False

        def main() -> str:
            values = [3]
            represented = [int8(3)]
            return str(([Box()] == values, values == [Box()],
                        [1].__eq__([1]), (1,).__ne__((2,)),
                        {'a': 1}.__eq__({'a': 1}),
                        {1}.__eq__(frozenset([1])), frozenset([1]).__ne__({2}),
                        represented == [int8(3)], represented != [int8(4)]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_represented_items_can_use_default_object_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect

        class Plain:
            pass

        class NeOnly(Plain):
            def __ne__(self, other: object) -> bool:
                raise AssertionError('element inequality must not run')

        class Unrelated:
            def __eq__(self, other: object) -> bool:
                return True

        def compare(value: Plain) -> tuple[bool, bool, bool]:
            return ((value,) == (int8(3),), (int8(3),) == (value,),
                    (value,) != (int8(3),))

        def main() -> str:
            value = Plain()
            other = NeOnly()
            Unrelated()
            gc_collect()
            return str((compare(value), compare(other),
                        [[value]] == [[int8(3)]],
                        {'x': (value,)} != {'x': (int8(3),)},
                        (value,).__eq__((int8(3),)),
                        (other,).__ne__((int8(3),))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("method, expression", [
    ("__eq__", "(value,) == (int8(3),)"),
    ("__ne__", "value != [int8(3)]"),
])
def test_default_identity_does_not_hide_reached_subclass_callbacks(method, expression):
    with pytest.raises(LLVMUnsupported, match="object comparison callbacks require ordinary item representations"):
        transpile_llvm(f'''
            from pyjs import int8

            class Base:
                pass

            class Child(Base):
                def {method}(self, other: object) -> bool:
                    return True

            def compare(value: Base) -> bool:
                return {expression}

            def main() -> bool:
                return compare(Child())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_represented_siblings_do_not_cross_callback_boundary(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __eq__(self, other: object) -> bool:
                gc_collect()
                return isinstance(other, Box)

        def optional(left: tuple[Box, int8] | None, right: tuple[Box, int8] | None) -> bool:
            return left == right

        def main() -> str:
            gc_set_threshold(1)
            left = (Box(), int8(3))
            right = (Box(), int8(3))
            keys = {int8(3): Box()}
            erased_left: tuple[int8, object] = (int8(3), "x")
            erased_right: tuple[int8, object] = (int8(3), "x")
            return str((left == right, left != (Box(), int8(4)),
                        keys == {int8(3): Box()}, keys != {int8(4): Box()},
                        [left] == [right], {'x': left} == {'x': right},
                        left.__eq__(right), keys.__eq__({int8(3): Box()}),
                        optional(left, right), optional(left, None), optional(None, right),
                        erased_left == erased_right))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_callback_parameters_preserve_checked_binding(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Optional:
            def __eq__(self, other: int | None) -> bool:
                gc_collect()
                return other is None or other == 3

        class Either:
            def __eq__(self, other: int | str) -> bool:
                gc_collect()
                return other == 1 or other == "a"
            def __lt__(self, other: int | float) -> bool:
                if isinstance(other, int):
                    return other > 2
                return other > 2.0

        class ObjectOptional:
            def __eq__(self, other: object | None) -> bool:
                gc_collect()
                return other is None

        class Pair:
            def __eq__(self, other: "Pair | int") -> bool:
                return isinstance(other, Pair)

        class ContainerOptional:
            def __eq__(self, other: list[int] | None) -> bool:
                gc_collect()
                return other is None or other == [1, 2]

        class FloatOrText:
            def __eq__(self, other: float | str) -> bool:
                return other == 3

        class Numeric:
            def __eq__(self, other: float | int) -> bool:
                return other == 3 or str(other) == 'True'

        def main() -> str:
            gc_set_threshold(1)
            return str((Optional() == 3, 4 == Optional(), Optional() == None,
                        None == Optional(), [None] == [Optional()],
                        [Optional()] == [3], Optional() != 3,
                        Either() == 1, "a" == Either(), [Either()] == [1],
                        (Either(), 2) == ("b", 2), {'k': Either()} == {'k': 1},
                        Either() < 1, Either() < 2.5, 3 > Either(),
                        ObjectOptional() == 3, None == ObjectOptional(),
                        ContainerOptional() == None, [[1, 2]] == [ContainerOptional()],
                        Pair() == Pair(), Pair() == 1, 1 == Pair(),
                        [FloatOrText()] == [3.0], ['x'] == [FloatOrText()],
                        FloatOrText() == float(3), [Numeric()] == [3],
                        [True] == [Numeric()]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("annotation, value", [
    ("list[int] | None", "[True]"), ("tuple[int, str] | None", "(True, 'a')"),
])
def test_union_callback_does_not_reinterpret_container_storage(annotation, value):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
            class Box:
                def __eq__(self, other: {annotation}) -> bool:
                    return other is None

            def main() -> bool:
                return [Box()] == [{value}]
        ''')


def test_numeric_heterogeneous_ordering_preserves_values():
    # Numeric structural ordering now compares the actual scalar kinds rather
    # than requiring identical element storage (the former boundary here).
    LLVM().assert_matches_python('''
        def main() -> str:
            return str(([True] < [1], [False] <= [0], [2] > [True], [0] >= [True]))
    ''')


@pytest.mark.parametrize("expression", ["value != 42", "42 != value"])
def test_inequality_fallback_respects_explicit_argument_annotation(expression):
    with pytest.raises(CompilationError, match="Operator '!=' is not supported"):
        transpile_llvm(f'''
            class Value:
                def __eq__(self, other: object) -> bool:
                    return True

                def __ne__(self, other: str) -> bool:
                    return False

            def main() -> bool:
                value = Value()
                return {expression}
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_callbacks_retain_boxed_values_after_return(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Keep:
            def __init__(self):
                self.saved: list[object] = []

            def __eq__(self, other: object) -> bool:
                gc_collect()
                self.saved.append(other)
                return True

        def fill(value: Keep) -> None:
            assert [value] == [1000]
            assert ["created" + str(1)] == [value]
            assert [[2, 3]] == [value]
            assert [value] == [{"a": 4}]
            assert not (value != (5, "six"))

        def main() -> str:
            gc_set_threshold(1)
            value = Keep()
            fill(value)
            gc_collect()
            return repr(value.saved)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_reflection_preserves_operand_order_and_failure(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Match:
            def __init__(self, events: list[str]):
                self.events = events

            def __eq__(self, other: int) -> bool:
                gc_collect()
                self.events.append("eq")
                return other == 42

            def __ne__(self, other: int) -> bool:
                gc_collect()
                self.events.append("ne")
                return other != 42

        def left(events: list[str], fail: bool) -> int:
            events.append("left")
            if fail:
                raise ValueError("left failed")
            return 42

        def right(events: list[str], fail: bool) -> Match:
            events.append("right")
            gc_collect()
            if fail:
                raise ValueError("right failed")
            return Match(events)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            answers = [left(events, False) == right(events, False),
                       left(events, False) != right(events, False)]
            for mode in range(2):
                try:
                    answers.append(left(events, mode == 0) == right(events, mode == 1))
                except ValueError as error:
                    events.append(str(error))
            answers.append(left(events, False) == right(events, False))
            return str((answers, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_comparison_boxing_failure_does_not_invoke_callback(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        class Value:
            def __init__(self):
                self.calls = 0

            def __eq__(self, other: object) -> bool:
                self.calls += 1
                {'gc_collect()' if managed else 'pass'}
                return True

        def main() -> int:
            value = Value()
            left = [value]
            integers = [1000]
            strings = ["café"]
            mapping = {{1: 7}}
            for mode in range(3):
                caught = False
                arm(1)
                try:
                    if mode == 0:
                        left == integers
                    elif mode == 1:
                        left == strings
                    else:
                        mapping == value
                except MemoryError:
                    caught = True
                arm(0)
                {'gc_collect()' if managed else 'pass'}
                if not caught or value.calls != 0:
                    return 1
            if not (left == integers and left == strings and mapping == value):
                return 2
            return 0 if value.calls == 3 else 3
    ''')
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_comparisons_reflect_to_object_parameters(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Match:
            def __init__(self, events: list[str]):
                self.events = events

            def __eq__(self, other: object) -> bool:
                gc_collect()
                self.events.append("eq:" + repr(other))
                return True

        class Different(Match):
            def __ne__(self, other: object) -> bool:
                gc_collect()
                self.events.append("ne:" + repr(other))
                return True

        class Declared(Match):
            def __ne__(self, other: object) -> bool:
                return not self.__eq__(other)

        class Override(Declared):
            def __ne__(self, other: object) -> bool:
                gc_collect()
                self.events.append("override:" + repr(other))
                return True

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            value = Match(events)
            other = Different(events)
            inherited: Declared = Override(events)
            results = [42 == value, 42 != value, 2.5 == value,
                       True == value, None == value, "café" == value,
                       b"bytes" == value, [1] == value, (2,) == value,
                       {"one": 1} == value, {3} == value, frozenset([4]) == value,
                       42 != other, [1] != other, value == 42, other != 42,
                       value != 42, inherited != 42, None != value, value != None,
                       value.__eq__(42), Declared(events).__ne__(42)]
            return str((results, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inequality_finds_methods_added_below_eq_only_base(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, events: list[str], name: str):
                self.events = events
                self.name = name

            def __eq__(self, other: object) -> bool:
                gc_collect()
                self.events.append("eq:" + self.name)
                return True

        class Child(Base):
            def __ne__(self, other: object) -> bool:
                gc_collect()
                self.events.append("ne:" + self.name)
                if self.name == "error":
                    raise ValueError("comparison")
                return True

        class Grandchild(Child):
            pass

        class EqChild(Base):
            def __eq__(self, other: object) -> bool:
                gc_collect()
                self.events.append("override-eq:" + self.name)
                return False

        class Unrelated:
            def __init__(self):
                self.value = 99

            def __ne__(self, other: object) -> bool:
                return unavailable_in_native(other)

        def compare(value: Base) -> list[bool]:
            return [value != 42, 42 != value, b"bytes" != value,
                    [1] != value, {"one": 1} != value]

        def pair(left: Base, right: Base) -> bool:
            return left != right

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            base = Base(events, "base")
            answers = compare(base)
            child = Child(events, "child")
            grandchild = Grandchild(events, "grandchild")
            eq_child = EqChild(events, "eq-child")
            Unrelated()
            answers.extend(compare(child))
            answers.extend(compare(grandchild))
            answers.append(pair(base, child))
            answers.append(pair(child, base))
            answers.append(pair(child, grandchild))
            answers.append(pair(child, child))
            answers.append(pair(base, eq_child))
            answers.append(pair(eq_child, base))
            answers.extend(compare(eq_child))
            try:
                compare(Child(events, "error"))
            except ValueError as error:
                events.append(str(error))
            gc_collect()
            answers.append(pair(base, child))
            return str((answers, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
