import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_defaults_are_packed_into_the_declared_union_layout(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import date
        from pyjs.native import gc_collect, gc_set_threshold

        def tagged(value: int | str = 4, *, label: str | int = "default") -> str:
            gc_collect()
            return str(value) + str(label)

        def optional(value: int | None = None) -> str:
            return str(value)

        def main() -> str:
            gc_set_threshold(1)
            empty: list[int] = []
            named: dict[str, int] = {}
            supplied: list[int | None] = [None, 7]
            return (tagged(*empty) + tagged(**named) + tagged(*[2]) +
                    optional(*empty) + optional(*supplied[:1]) + optional(*supplied[1:]) +
                    str(date(2024, 1, 2).replace(*[2025])))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_calls_bind_defaults_packs_and_concrete_iterables(optimize):
    LLVM().assert_matches_python('''
    def fixed(a: int, b: int = 7, *, extra: int = 2) -> int:
        return a * 100 + b * 10 + extra

    def collect(a: int, /, *values: int, extra: int = 2, **named: int) -> int:
        return a + sum(values) + extra + sum(named.values())

    def mixed(label: str, value: int, *weights: float, suffix: str = "!") -> str:
        return label + str(value) + str(sum(weights, 0.0)) + suffix

    def main() -> str:
        short = [1]
        full = [1, 3]
        named = {"b": 4, "extra": 5}
        result = str(fixed(*short)) + ":" + str(fixed(*full, extra=6))
        result += ":" + str(fixed(2, **named))
        assert fixed(*range(1, 3)) == 122
        assert fixed(*iter(full)) == 132
        assert fixed(*{"a": 1, "b": 2}.values()) == 122
        assert collect(*short, 4, *full, extra=3, other=2) == 14
        assert collect(1, *[], **{"a": 5, "other": 2}) == 10
        assert mixed(*("label", 3), *[1.5, 2.5], suffix="?") == "label34.0?"
        assert mixed(**{"label": "dict", "value": 3, "suffix": "?"}) == "dict30.0?"
        return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_calls_preserve_merging_and_consumption_order(optimize):
    LLVM().assert_matches_python('''
    def accept(*values: int, **named: int) -> str:
        return str(sum(values)) + ":" + "".join(named.keys())

    def mutate(values: list[int]) -> int:
        values.append(2)
        return 9

    def effect(events: list[int], value: int) -> int:
        events.append(value)
        return value

    def only(a: int, *, b: int = 3) -> int:
        return a + b

    def main() -> str:
        values = [1]
        assert accept(*values, changed=mutate(values)) == "3:changed"
        values = [1]
        assert accept(0, *values, changed=mutate(values)) == "1:changed"
        events: list[int] = []
        mapping = {"a": 1}
        try:
            accept(**mapping, a=effect(events, 2), b=effect(events, 3))
        except TypeError:
            assert events == [2, 3]
        else:
            raise AssertionError("duplicate keyword")
        events.clear()
        assert accept(**{"a": effect(events, 1), "a": effect(events, 2)}) == "0:a"
        assert events == [1, 2]
        events.clear()
        try:
            accept(**mapping, **mapping, last=effect(events, 4))
        except TypeError:
            assert events == []
        else:
            raise AssertionError("duplicate expansion")
        source = iter([1, 2])
        try:
            accept(*source, **mapping, **mapping)
        except TypeError:
            assert next(source) == 1
        else:
            raise AssertionError("merge must fail before lone-star consumption")
        source = iter([1, 2, 3])
        try:
            only(*source, b=effect(events, 5))
        except TypeError:
            assert events == [5]
            assert next(source, 99) == 99
        else:
            raise AssertionError("excess arguments")
        events.clear()
        try:
            only(*[1], a=effect(events, 6), b=effect(events, 7))
        except TypeError:
            assert events == [6, 7]
        else:
            raise AssertionError("parameter binding must follow all operand effects")
        return accept(**{"c": 3}, a=1, b=2, **{"d": 4})
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind, value", [("int8", "127"), ("int64", "9007199254740993"), ("float32", "16777216.0")])
def test_static_array_expansion_retains_scalar_and_nested_representations(optimize, kind, value):
    LLVM().assert_matches_python(f'''
    from pyjs import StaticArray, {kind}

    def scalar(value: {kind}) -> {kind}:
        return value + 1

    def nested(value: StaticArray[{kind}, 1]) -> {kind}:
        return value[0] + 1

    def main() -> str:
        values = StaticArray[{kind}, 1]([{value}])
        rows = StaticArray[StaticArray[{kind}, 1], 1]([values])
        return str(scalar(*values)) + ":" + str(nested(*rows))
    ''', optimize=optimize)


@pytest.mark.parametrize("nested", [False, True])
def test_static_array_expansion_rejects_representation_erasure(nested):
    annotation = "list[int]" if nested else "int"
    expression = "value[0] + 1" if nested else "value + 1"
    argument = "rows" if nested else "values"
    with pytest.raises(LLVMUnsupported, match="matching parameter representations"):
        transpile_llvm(f'''
        from pyjs import StaticArray, int8

        def target(value: {annotation}) -> int:
            return {expression}

        def main() -> str:
            values = StaticArray[int8, 1]([127])
            rows = StaticArray[StaticArray[int8, 1], 1]([values])
            return str(target(*{argument}))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("cursor", [False, True], ids=["view", "iterator"])
@pytest.mark.parametrize("kind, value", [("int8", "127"), ("int64", "9007199254740993"), ("float32", "16777216.0")])
def test_mapping_view_expansion_preserves_item_representations(optimize, cursor, kind, value):
    view = "iter(view)" if cursor else "view"
    LLVM().assert_matches_python(f'''
    from pyjs import float32, int8, int64, StaticArray

    def scalar(value: {kind}) -> str:
        return str(value + 1)

    def key(value: int8) -> str:
        return str(value + 1)

    def pair(value: tuple[int8, {kind}]) -> str:
        return str(value[0] + 1) + ":" + str(value[1] + 1)

    def nested(value: StaticArray[{kind}, 1]) -> str:
        return str(value[0] + 1)

    def main() -> str:
        mapping = {{int8(127): {kind}({value})}}
        keys_view = mapping.keys()
        values_view = mapping.values()
        items_view = mapping.items()
        nested_mapping = {{"a": StaticArray[{kind}, 1]([{value}])}}
        nested_view = nested_mapping.values()
        return (key(*{view.replace('view', 'keys_view')}) + ":"
                + scalar(*{view.replace('view', 'values_view')}) + ":"
                + pair(*{view.replace('view', 'items_view')}) + ":"
                + nested(*{view.replace('view', 'nested_view')}))
    ''', optimize=optimize)


@pytest.mark.parametrize("cursor", [False, True], ids=["view", "iterator"])
@pytest.mark.parametrize("view", ["keys", "values", "items"])
def test_mapping_view_expansion_rejects_erased_representation(cursor, view):
    argument = f"mapping.{view}()"
    if cursor:
        argument = f"iter({argument})"
    annotation = "tuple[int, int]" if view == "items" else "int"
    value = "value[1]" if view == "items" else "value"
    with pytest.raises(LLVMUnsupported, match="matching parameter representations"):
        transpile_llvm(f'''
        from pyjs import int8

        def target(value: {annotation}) -> str:
            return str({value} + 1)

        def main() -> str:
            mapping = {{int8(127): int8(127)}}
            return target(*{argument})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_annotated_item_view_expansion_keeps_asymmetric_fields(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import ItemsView
        from pyjs import int8, int64

        def pair(value: tuple[int8, int64]) -> str:
            return str(value[0] + 1) + ":" + str(value[1] + 1)

        def forward(view: ItemsView[int8, int64]) -> str:
            return pair(*view) + ":" + pair(*view.__iter__())

        def main() -> str:
            values = {int8(127): int64(127)}
            return forward(values.items())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_implicit_constructor_expansion_effects_errors_and_recovery(optimize):
    LLVM().assert_matches_python('''
    from pyjs.native import gc_collect, gc_set_threshold

    class Empty:
        pass

    def effect(events: list[int], value: int) -> int:
        events.append(value)
        gc_collect()
        return value

    def keywords(events: list[int], values: list[int]) -> dict[str, int]:
        events.append(2)
        values.clear()
        gc_collect()
        return {}

    def main() -> int:
        gc_set_threshold(1)
        events: list[int] = []
        values = [1]
        first = Empty(*values, **keywords(events, values))
        assert events == [2]
        assert first is not Empty(*[], **{})
        empty: dict[str, int] = {}
        assert Empty(**empty) is not first
        failures = 0
        positional_cases: list[list[int]] = [[], [1]]
        for values in positional_cases:
            source = iter(values)
            try:
                Empty(*source)
            except TypeError:
                failures += 1
            assert next(source, 9) == 9
        keyword_cases: list[dict[str, int]] = [{}, {"value": 1}]
        for named in keyword_cases:
            try:
                Empty(**named)
            except TypeError:
                failures += 1
        events.clear()
        try:
            Empty(*[effect(events, 1)], value=effect(events, 2))
        except TypeError:
            assert events == [1, 2]
            failures += 1
        gc_collect()
        assert Empty(*[]) is not first
        return failures
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_literal_keywords_remain_supported(optimize):
    LLVM().assert_matches_python('''
    from math import isclose

    def main() -> str:
        assert isclose(1.0, 1.1, **{"rel_tol": 0.2})
        return str(sum([1, 2], **{"start": 3})) + ":" + str(round(**{"number": 1.5}))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shadowed_builtin_retains_runtime_keyword_binding(optimize):
    LLVM().assert_matches_python('''
    def sum(*values: int, **named: int) -> int:
        return values[0] + named["start"]

    def main() -> int:
        named = {"start": 2}
        return sum(*[1], **named)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_binding_errors_are_catchable_and_recoverable(optimize):
    LLVM().assert_matches_python('''
    from pyjs.native import gc_collect, gc_set_threshold

    def required(a: int, /, b: int, *, c: int) -> int:
        return a + b + c

    def positional(a: int, /, **options: int) -> int:
        return a

    def main() -> int:
        gc_set_threshold(1)
        failures = 0
        cases: list[list[int]] = [[], [1], [1, 2], [1, 2, 3]]
        for arguments in cases:
            try:
                required(*arguments)
            except TypeError:
                failures += 1
            gc_collect()
        for keywords in [{"c": 2, "b": 3}, {"c": 2, "a": 3}, {"c": 2, "unknown": 3}]:
            try:
                required(*[1, 2], **keywords)
            except TypeError:
                failures += 1
            gc_collect()
        try:
            positional(**{"a": 1})
        except TypeError:
            failures += 1
        assert failures == 8
        return required(*[1], **{"b": 2, "c": 3})
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_constructors_virtual_methods_and_gc_retention(optimize):
    LLVM().assert_matches_python('''
    from pyjs.native import gc_collect, gc_set_threshold

    class Parent:
        def __init__(self, *values: str, **named: str):
            self.values = values
            self.named = named

        def show(self, *extra: str, **named: str) -> str:
            return "".join(self.values) + "".join(extra) + "".join(named.values())

    class Child(Parent):
        def show(self, *extra: str, **named: str) -> str:
            return "child:" + super().show(*extra, **named)

    def use(parent: Parent, values: list[str], named: dict[str, str]) -> str:
        return parent.show(*values, **named)

    def later(values: list[str]) -> str:
        values.clear()
        gc_collect()
        return "later"

    def main() -> str:
        gc_set_threshold(1)
        values = ["first" + "!"]
        parent = Child("prefix", *values, last=later(values))
        gc_collect()
        assert parent.values == ("prefix", "first!")
        assert parent.named["last"] == "later"
        values = ["extra" + "!"]
        named = {"last": "named" + "!"}
        return use(parent, values, named)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansion_static_inline_and_nested_parameter_boundaries(optimize):
    LLVM().assert_matches_python('''
    from pyjs import llvm

    class Base:
        def __init__(self, value: int):
            self.value = value

        @staticmethod
        def add(value: int, *, extra: int = 2) -> int:
            return value + extra

    class Child(Base):
        pass

    def read(value: Base) -> int:
        return value.value

    def nested(values: list[tuple[int, ...]]) -> int:
        return sum(values[0])

    @llvm.inline("{value}")
    def identity(value: int) -> int:
        return value

    def main() -> int:
        values: list[tuple[int, ...]] = [(1, 2, 3)]
        assert nested(*[values]) == 6
        assert read(*[Child(4)]) == 4
        assert identity(**{"value": 7}) == 7
        return Base.add(*[identity(*[5])], **{"extra": 3})
    ''', optimize=optimize)


@pytest.mark.parametrize("source, message", [
    ('''def target(value: str) -> int: return len(value)
def main() -> int: return target(*[1])''', "requires its declared type and storage; use an explicit conversion"),
    ('''def target(**values: int) -> int: return len(values)
def main() -> int: return target(**{1: 2})''', "string-keyed dict"),
    ('''def target(value: float) -> str: return str(value)
def main() -> str: return target(*[1])''', "requires its declared type and storage; use an explicit conversion"),
    ('''def target(value: int) -> str: return str(value)
def main() -> str: return target(**{"value": True})''', "requires its declared type and storage; use an explicit conversion"),
    ('''def target(value: list[int]) -> int: return value[0]
def main() -> int: return target(*[[True]])''', "matching concrete item storage"),
    ('''class Box:
    def __init__(self, number: int): self.number = number
def target(value: list[Box]) -> int: return value[0].number
def main() -> int: return target(**{"value": ["not a Box"]})''', "matching concrete item storage"),
])
def test_expansions_reject_unsafe_storage(source, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(source)


@pytest.mark.parametrize("annotation, value", [("str", "1"), ("int8", "int16(1)"), ("int", "int8(1)")])
@pytest.mark.parametrize("shape", ["iterable", "tuple", "keywords", "variadic"])
def test_expanded_parameter_storage_is_checked_before_native_execution(annotation, value, shape):
    # Dynamic binding is checked by native lowering, not the shared analyzer's
    # old positional approximation. Neither numeric widths nor ordinary/portable
    # distinctions may disappear through an expansion.
    setup, argument = {
        "iterable": (f"values = [{value}]", "*values"),
        "tuple": (f"values = ({value},)", "*values"),
        "keywords": (f"values = {{'value': {value}}}", "**values"),
        "variadic": (f"values = [{value}]", "*values"),
    }[shape]
    parameter = "*value" if shape == "variadic" else "value"
    message = ("declared type and storage" if annotation == "str" else "matching parameter representations")
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
from pyjs import int8, int16
def target({parameter}: {annotation}) -> str:
    return str(value)
def main() -> str:
    {setup}
    return target({argument})
''')


def test_dynamic_keywords_reject_ambiguous_numeric_representations():
    with pytest.raises(LLVMUnsupported, match="matching parameter representations"):
        transpile_llvm('''
        from pyjs import int8, int64

        def target(a: int8, b: int64 = int64(0)) -> int:
            return int(a) + int(b)

        def main() -> int:
            values = {"a": int8(1)}
            return target(**values)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansion_representation_and_runtime_tuple_lengths(optimize):
    LLVM().assert_matches_python('''
    from pyjs import int8, int64, float32, llvm

    def represented(a: int8, /, *values: int8, extra: int64, **weights: float32) -> str:
        return str(a + sum(values, int8(0))) + str(extra) + str(sum(weights.values(), float32(0)))

    @llvm.inline("{values}")
    def fixed_view(values: tuple[int, ...]) -> tuple[int, int]:
        return values

    def total_weights(**weights: float32) -> float32:
        return sum(weights.values(), float32(0))

    def collect(*values: int) -> int:
        return sum(values)

    def main() -> str:
        values = [int8(120), int8(20)]
        weights = {"one": float32(1.5), "two": float32(2.5)}
        assert collect(*fixed_view((1, 2, 3))) == 6
        assert collect(*fixed_view(())) == 0
        assert total_weights(**weights) == float32(4)
        return represented(*values, extra=int64(9007199254740993), one=float32(1.5), two=float32(2.5))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_parameter_roots_survive_source_mutation_and_nested_calls(optimize):
    LLVM().assert_matches_python('''
    from pyjs.native import gc_collect, gc_set_threshold

    class Box:
        def __init__(self, text: str):
            self.text = text

    def take(first: Box, second: Box) -> str:
        gc_collect()
        return first.text + second.text

    def mutate(values: list[Box], named: dict[str, Box]) -> Box:
        values.clear()
        named.clear()
        gc_collect()
        return Box("second" + "!")

    def collect(*items: str) -> str:
        gc_collect()
        return "".join(items)

    def fail() -> int:
        try:
            return no_arguments(*range(1))
        finally:
            gc_collect()

    def no_arguments() -> int:
        return 0

    def main() -> str:
        gc_set_threshold(1)
        values = [Box("first" + "!")]
        named: dict[str, Box] = {}
        # An additional positional operand forces eager star materialization.
        result = take(*values, mutate(values, named))
        named = {"first": Box("named" + "!")}
        result += take(**named, second=mutate(values, named))
        result += collect(*["outer" + "!"], *[collect(*["inner" + "!"])])
        try:
            fail()
        except TypeError:
            gc_collect()
        return result
    ''', optimize=optimize)


@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "gc-stress"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_expansion_allocation_failures_unwind_and_retry(tmp_path, managed, optimize):
    from tests.native.allocation_support import run_allocation_case

    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def collect(first: str, *values: str, extra: str = "default", **named: str) -> str:
    return first + "".join(values) + extra + "".join(named.values())

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    values = ["a" + "!", "b" + "!", "c" + "!"]
    named = {{"extra": "e" + "!", "last": "z" + "!"}}
    failures = 0
    for attempt in range(1, 100):
        arm(attempt)
        complete = False
        try:
            result = collect(*values, **named)
            arm(0)
            assert result == "a!b!c!e!z!"
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert values == ["a!", "b!", "c!"]
        assert named == {{"extra": "e!", "last": "z!"}}
        assert collect(*values, **named) == "a!b!c!e!z!"
        if complete:
            return 0 if failures else 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_unions_convert_and_root_values_before_later_callbacks(tmp_path, optimize):
    LLVM().assert_matches_python('''
    from pyjs.native import gc_collect, gc_set_threshold

    def collect(first: str | int, *values: str | int, tail: str | int = 0, **named: str | int) -> str:
        gc_collect()
        return str((first, values, tail, named))

    def replace(source: list[str]) -> int:
        source.clear()
        gc_collect()
        return 9

    def main() -> str:
        gc_set_threshold(1)
        source = ["owned" + str(7)]
        extra: list[str | int] = ["text", 2]
        named: dict[str, str | int] = {"one": "first", "two": 2}
        return collect(source[0], *extra, tail=replace(source), **named)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
