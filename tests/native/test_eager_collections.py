import textwrap

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.testing.helpers import analyze_module_source
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import EAGER_COLLECTION_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_eager_collection_contract(optimize):
    result = LLVM().assert_matches_python(EAGER_COLLECTION_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, EAGER_COLLECTION_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [
    '''
    def main() -> str:
        values = list(range(-3, 6, 2))
        copy = list(values)
        copy.append(20)
        empty: list[int] = list()
        empty.append(4)
        result = str(len(copy)) + str(len(values)) + str(empty[0])
        for value in list((9, 3, 8)):
            result += str(value)
        for value in list(b"a\\x00\\xff"):
            result += str(value) + ","
        for character in list("aé😀"):
            result += character + ":"
        return result
    ''',
    '''
    def main() -> str:
        values = {"a": 2, "b": 3}
        keys = values.keys()
        items = values.items()
        members = values.values()
        values["a"] = 9
        values["c"] = 4
        result = str(len(keys)) + str(len(items)) + str(len(members))
        result += str("b" in keys) + str(9 in members) + str(("c", 4) in items)
        for key in keys:
            result += key
        for value in members:
            result += str(value)
        for key, value in items:
            result += key + str(value)
        return result + str(sum(members))
    ''',
    '''
    def main() -> str:
        values: dict[str, int] = dict()
        values["z"] = 5
        copy = dict(values)
        copy["x"] = 7
        pairs = [("a", 1), ("b", 3), ("a", 9)]
        built = dict(pairs)
        result = str(built == {"a": 9, "b": 3}) + str(built != {"b": 3})
        result += str(copy == {"x": 7, "z": 5}) + str(len(values))
        merged = built | {"a": 4, "c": 6}
        alias = merged
        merged |= {"a": 8, "d": 2}
        for key in alias:
            result += key + str(alias[key])
        pair = merged.popitem()
        return result + pair[0] + str(pair[1]) + str(len(merged))
    ''',
    '''
    def main() -> str:
        values: set[int] = set()
        values.add(3)
        a = set([1, 2, 2, 3])
        b = {3, 4}
        result = str(a | b == {1, 2, 3, 4})
        result += str(a & b == {3}) + str(a - b == {1, 2})
        result += str(a ^ b == {1, 2, 4})
        result += str(a.union([3, 4], (4, 5)) == {1, 2, 3, 4, 5})
        result += str(a.intersection([2, 3, 4], (3, 5)) == {3})
        result += str(a.difference([1], (3,)) == {2})
        result += str(a.symmetric_difference([3, 4, 4]) == {1, 2, 4})
        result += str(values < a) + str(a > values) + str(values <= a)
        result += str(a.issuperset(values)) + str(values.issubset([2, 3]))
        result += str(a.isdisjoint([8, 9])) + str(a.isdisjoint([3, 9]))
        alias = a
        a |= b
        a &= {2, 3, 4}
        a -= {4}
        a ^= {2, 8}
        result += str(alias == {3, 8})
        alias.difference_update(alias)
        return result + str(len(a))
    ''',
    '''
    def main() -> str:
        values = [4, 2, 2, -1, 5]
        alias = values
        copied = sorted(values)
        values.sort(reverse=True)
        result = str(alias == [5, 4, 2, 2, -1])
        result += str(copied == [-1, 2, 2, 4, 5])
        result += str([1, 2] < [1, 3]) + str([1, 2] <= [1, 2])
        result += str([1, 2] >= [1]) + str([2] > [1, 9])
        result += str([1] != [1, 2])
        for word in sorted(["😀", "é", "a", "é"]):
            result += word
        for number in sorted((3, 1, 2), reverse=True):
            result += str(number)
        return result
    ''',
    '''
    def main() -> str:
        empty: list[int] = []
        result = str(sum(empty)) + str(sum(range(-3, 5)))
        result += str(sum([1, 2, 3], start=5))
        result += str(min([3, -1, 4])) + str(max((3, 7, 2)))
        result += str(min(4, 7, 2)) + str(max(4, 7, 2))
        result += min(["é", "a", "😀"]) + max(["é", "a", "😀"])
        result += str(min(empty, default=9)) + str(max(empty, default=-9))
        result += str(any(empty)) + str(all(empty))
        result += str(any([0, 2, 0])) + str(all([2, 0, 3]))
        result += str(any(["", "x"])) + str(all(["a", "x"]))
        result += str(sum({2: 10, 4: 20}))
        return result
    ''',
    '''
    def main() -> str:
        values = (1, "é", 3, 1)
        result = str(len(values)) + str(1 in values) + str("z" in values)
        result += str(values.count(1)) + str(values.index("é"))
        result += str(values == (1, "é", 3, 1))
        result += str(values != (2, "é", 3, 1))
        for value in (2, 3, 4):
            result += str(value)
        return result
    ''',
], ids=["construction", "live-views", "mappings", "sets", "ordering", "reductions", "tuples"])
def test_eager_collection_scenarios(source, optimize):
    LLVM().assert_matches_python(source, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_eager_errors_preserve_live_state_and_allow_recovery(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values = {"a": "é", "b": "😀"}
            view = values.items()
            result = ""
            try:
                for key, value in view:
                    result += value
                    values["c"] = "added"
            except RuntimeError:
                result += "mutation;"
            gc_collect()
            copied = dict(values)
            copied.clear()
            try:
                copied.popitem()
            except KeyError:
                result += "empty;"
            empty: list[int] = []
            try:
                min(empty)
            except ValueError:
                result += "minimum;"
            try:
                (1, 2).index(8)
            except ValueError:
                result += "index;"
            for key in sorted(values.keys()):
                result += key + values[key]
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_views_retain_temporary_mappings_and_observe_mutation(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import ItemsView
        from pyjs.native import gc_collect, gc_set_threshold

        def make_view(index: int) -> ItemsView[str, str]:
            return {"key" + str(index): "value" + str(index)}.items()

        def main() -> str:
            gc_set_threshold(1)
            view = make_view(5)
            gc_collect()
            result = ""
            for key, value in view:
                gc_collect()
                result += key + value
            mapping = {"a": 1}
            keys = mapping.keys()
            other = mapping.keys()
            assert keys is not other
            assert bool(keys) and bool(mapping.values()) and bool(mapping.items())
            mapping.clear()
            assert not keys and not mapping.values() and not mapping.items()
            mapping["z"] = 4
            gc_collect()
            return result + str(len(keys)) + str(sum(mapping.values()))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_eager_arguments_and_defaults_run_once_in_source_order(optimize):
    LLVM().assert_matches_python('''
        def values(events: list[str]) -> list[int]:
            events.append("values")
            return [3, 1, 2]

        def reverse(events: list[str]) -> bool:
            events.append("reverse")
            return True

        def fallback(events: list[str]) -> int:
            events.append("fallback")
            return 9

        def member(events: list[str]) -> int:
            events.append("member")
            return 1

        def mapping(events: list[str]) -> dict[int, int]:
            events.append("mapping")
            return {1: 3}

        def main() -> str:
            events: list[str] = []
            assert sorted(values(events), reverse=reverse(events)) == [3, 2, 1]
            assert min(values(events), default=fallback(events)) == 1
            assert member(events) in mapping(events).keys()
            assert member(events) in list(values(events))
            assert sum(values(events), start=fallback(events)) == 15
            return ",".join(events)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_portable_reductions_and_float_compensation(optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, int64, uint32, float32

        def main() -> str:
            narrow = [int8(120), int8(10)]
            wide = [int64(9007199254740993), int64(2)]
            singles = [float32(16777216.0), float32(1.0), float32(-16777216.0)]
            assert sum(narrow, int8(0)) == int8(-126)
            assert sum(wide, int64(0)) == int64(9007199254740995)
            assert sum(singles, float32(0.0)) == float32(0.0)
            assert sorted(narrow)[0] == int8(10)
            assert max(wide) == int64(9007199254740993)
            unsigned = [uint32(4294967295), uint32(1)]
            assert sum(unsigned, uint32(0)) == uint32(0)
            assert sorted(unsigned)[0] == uint32(1)
            assert sum([1e16, 1.0, -1e16]) == 1.0
            assert sum([True, False, True]) == 2
            assert sum([1, 2], True) == 4
            assert sum([1.5, 2.5], True) == 5.0
            assert sum([1, 2, 3], 0.5) == 6.5
            assert sum([1.5, 2.5], 2) == 6.0
            empty: list[float] = []
            assert sum(empty, 0.0) == 0.0
            return "ok"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_collection_aliases_and_bounded_tuple_search(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            members = {1, 2, 3}
            alias = members
            members.update(members)
            members.intersection_update(members)
            assert members == {1, 2, 3} and alias is members
            members.symmetric_difference_update(members)
            assert len(alias) == 0
            try:
                members.pop()
            except KeyError:
                members.add(8)
            assert members.pop() == 8
            values = [1, 2]
            values.extend(values)
            values += (3, 4)
            assert values == [1, 2, 1, 2, 3, 4]
            mapping = {"a": 1}
            mapping.update([("b", 2), ("a", 3)])
            mapping.update(mapping)
            assert mapping == {"a": 3, "b": 2}
            pair = mapping.popitem()
            assert pair == ("b", 2)
            items = (1, 2, 1, 3)
            assert items.index(1, 1) == 2
            assert items.index(1, -3, -1) == 2
            try:
                items.index(1, 1, 2)
            except ValueError:
                return "ok"
            return "missed bounds"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_character_iteration_and_iterable_mutations(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            characters: list[str] = []
            characters.extend("aé😀")
            characters += "z"
            members = {"a"}
            members.update("é😀")
            assert members.union("z") == {"a", "é", "😀", "z"}
            result = ""
            for character in "aé😀":
                result += character + ":"
            for value in b"a\\x00\\xff":
                result += str(value) + ","
            return result + "".join(characters)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, start, values", [
    ("float", "", "[1.25, 2.5]"),
    ("float", ", 2", "[1.25, 2.5]"),
    ("float", ", 9223372036854775807", "[0.0]"),
    ("float", ", start=-0.0", "[-0.0]"),
    ("float", ", start=True", "[1e16, 1.0, -1e16]"),
    ("int", ", True", "[1, 2]"),
    ("bool", ", start=False", "[True, False]"),
])
def test_potentially_empty_sum_preserves_the_start_type(tmp_path, optimize, annotation, start, values):
    result = LLVM().assert_matches_python(f'''
        def total(values: list[{annotation}]) -> str:
            value = sum(values{start})
            return repr(value) + ":" + str(type(value) is bool) + ":" + str(type(value) is int)

        def main() -> str:
            empty: list[{annotation}] = []
            return total(empty) + "|" + total({values})
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("values, start", [("[1.0]", ""), ("[1]", ""), ("[1.0]", ", start=0.0")])
def test_sum_requires_a_positional_iterable(values, start):
    with pytest.raises(LLVMUnsupported, match="LLVM sum requires a positional iterable") as caught:
        transpile_llvm(f'''
            def main() -> str:
                return repr(sum(values={values}{start}))
        ''')
    assert str(caught.value) == "LLVM sum requires a positional iterable at line 2"
    assert any("_pyjs_native_.py:3:17" in note for note in caught.value.__notes__)


@pytest.mark.parametrize("expression, expected", [
    ("sum(floats)", "int|float"),
    ("sum(floats, start=True)", "bool|float"),
    ("sum(integers, True)", "bool|int"),
    ("sum(floats, 0.0)", "float"),
    ("sum([0.5])", "float"),
    ("sum(integers)", "int"),
])
def test_sum_analysis_preserves_empty_and_nonempty_result_types(expression, expected):
    with analyze_source(f'''
        def total(floats: list[float], integers: list[int]):
            return {expression}
        def main() -> str:
            return repr(total([0.5], [1]))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        total = analysis.entry_point.container.search("total")
        assert total.return_type.to_annotation_str() == expected


@pytest.mark.parametrize("annotation, start", [("int | float", "0"), ("bool | float", "False")])
def test_sum_union_start_keeps_a_located_representation_boundary(annotation, start):
    with pytest.raises(LLVMUnsupported, match="potentially empty iterable requires a matching start type") as caught:
        transpile_llvm(f'''
            def total(start: {annotation}) -> str:
                values: list[float] = []
                return repr(sum(values, start))
            def main() -> str:
                return total({start})
        ''')
    assert caught.value.node.lineno == 3


@pytest.mark.parametrize("optimize", [0, 2])
def test_sum_result_types_through_containers_calls_and_generator_effects(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Iterator

        EVENTS: list[str] = []

        def source(values: list[float]) -> Iterator[float]:
            EVENTS.append("source")
            return iter(values)

        def start() -> int:
            EVENTS.append("start")
            return 2

        def total(values: list[float]):
            return sum(source(values), start=start())

        def integers(values: list[int]):
            return sum(values, True)

        def values(count: int) -> Iterator[float]:
            for index in range(count):
                EVENTS.append(str(index))
                yield 0.5

        def main() -> str:
            empty: list[float] = []
            empty_int: list[int] = []
            empty_set: set[float] = set()
            mapping: dict[int, float] = {}
            empty_tuple: tuple[float, ...] = ()
            results = [repr(total(empty)), repr(total([0.5])),
                       repr(integers(empty_int)), repr(integers([2])),
                       repr(sum(empty_set)), repr(sum(mapping.values())),
                       repr(sum(empty_tuple)), repr(sum(values(0))), repr(sum(values(2)))]
            mapping[1] = 1.5
            results.append(repr(sum(mapping.values())))
            results.append(repr(float(total(empty)) + float(total([0.5]))))
            return "|".join(results) + ":" + ",".join(EVENTS)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_sum_preserves_integer_prefix_until_the_first_float(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            results: list[str] = []
            results.append(str(sum((9007199254740993, -9007199254740992, 0.0))))
            results.append(str(sum((9007199254740993, -9007199254740992, 0.5))))
            results.append(str(sum((-9007199254740992, 0.0), 9007199254740993)))
            results.append(str(sum((-9007199254740992, 0.5), start=9007199254740993)))
            results.append(str(sum((True, 9007199254740992, -9007199254740992, 0.5))))
            results.append(str(sum((0.0, 9007199254740993, -9007199254740992))))
            results.append(str(sum((9007199254740993, -9007199254740992), 0.0)))
            results.append(str(sum((9007199254740993, -9007199254740992, 0.5, 1e16, 1.0, -1e16))))
            return "|".join(results)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_sum_rounds_the_first_mixed_addition_before_compensation(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            results: list[str] = []
            results.append(str(sum((10000000000000000, 1.0, -1e16))))
            results.append(str(sum((1.0, -1e16), 10000000000000000)))
            results.append(str(sum([1.0, -1e16], start=10000000000000000)))
            results.append(str(sum((-10000000000000000, -1.0, 1e16))))
            results.append(str(sum([-1.0, 1e16], -10000000000000000)))
            results.append(str(sum((True, 1e16, 1.0, -1e16))))
            results.append(str(sum([1e16, 1.0, -1e16], True)))
            results.append(str(sum((1e16, 1.0, -1e16))))
            results.append(str(sum([1e16, 1.0, -1e16])))
            results.append(str(sum([1.0, -1e16], 1e16)))
            results.append(str(sum([-0.0])))
            results.append(str(sum([-0.0], -0.0)))
            return "|".join(results)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_container_equality_preserves_operand_evaluation(optimize):
    LLVM().assert_matches_python('''
        def sequence(events: list[str]) -> list[int]:
            events.append("list")
            return [1]

        def record(events: list[str]) -> tuple[int]:
            events.append("tuple")
            return (1,)

        def members(events: list[str]) -> set[int]:
            events.append("set")
            return {1}

        def main() -> str:
            events: list[str] = []
            assert not (sequence(events) == record(events))
            assert members(events) != sequence(events)
            assert sequence(events) != members(events)
            return "|".join(events)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_tuple_iteration_evaluates_source_without_rebinding_target(optimize):
    LLVM().assert_matches_python('''
        def empty(events: list[str]) -> tuple[()]:
            events.append("source")
            return ()

        def main() -> str:
            events: list[str] = []
            original = "original"
            value = original
            for value in empty(events):
                events.append("unreachable")
            else:
                events.append("else")
            literal = ()
            for unused in literal:
                events.append("unreachable")
                break
            else:
                events.append("literal else")
            assert value is original
            return "|".join(events)
    ''', optimize=optimize)


@pytest.mark.parametrize("body", [
    "return len(values)",
    "return 0",
    "return values[0]",
    "return sum(values)",
    "return len(list(values))",
    "total = 0\nfor value in values:\n    total += value\nreturn total",
])
def test_variadic_tuple_parameters_accept_fixed_tuple_views(body):
    source = "def consume(values: tuple[int, ...]) -> int:\n" + textwrap.indent(body, "    ")
    source += "\ndef main() -> int:\n    values = (1, 2, 3)\n    return consume(values)\n"
    LLVM().assert_matches_python(source)


@pytest.mark.parametrize("expression", [
    "(1,).__eq__(other=(1,))",
    "(1,).__ne__(other=(1,))",
    "{1: 2}.__eq__(other={1: 2})",
    "{1}.__or__(other=other(events))",
    "{1}.__iand__(other=other(events))",
    "{1}.__eq__(other=other(events))",
    "frozenset([1]).__eq__(other=other(events))",
    "[1].__eq__(other=[1])",
])
def test_collection_method_keywords_are_not_ignored(expression):
    source = '''
def other(events: list[int]) -> set[int]:
    events.append(1)
    return {2}

def main() -> str:
    events: list[int] = []
'''
    source += f"    return str({expression})\n"
    with pytest.raises(LLVMUnsupported, match="collection methods require positional arguments.*at line"):
        transpile_llvm(source)


@pytest.mark.parametrize("expression, diagnostic", [
    ("{1: 2}.__or__(other={2: 3})", "positional-only"),
    ("{1}.union(others={2})", "unexpected keyword argument"),
    ("{1: 2}.keys(unexpected=1)", "unexpected keyword argument"),
    ("{1}.__contains__(value=1)", "unexpected keyword argument"),
    ("{1}.issubset(other={2})", "positional-only"),
])
def test_invalid_collection_keywords_fail_during_analysis(expression, diagnostic):
    with pytest.raises(CompilationError, match=diagnostic) as caught:
        transpile_llvm(f"def main() -> str:\n    return str({expression})\n")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("analyze", [transpile_llvm, analyze_module_source])
@pytest.mark.parametrize("expression", [
    "{1}.issubset()", "{1}.issuperset()", "{1}.isdisjoint()",
    "{1}.__eq__()", "{1}.__contains__()", "{1}.__le__()",
])
def test_collection_comparison_hooks_validate_missing_operands(analyze, expression):
    with pytest.raises(CompilationError, match="missing required argument") as caught:
        analyze(f"def main() -> str:\n    return str({expression})\n")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("expression", [
    "{1}.issubset(other={1})", "{1}.issuperset(other={1})",
    "{1}.isdisjoint(other={1})", "{1}.__contains__(item=1)",
    "{1}.remove(item=1)", "{1}.discard(item=1)",
    "[1].index(item=1)", "[1].count(item=1)", "[1].remove(item=1)",
    "[1].__contains__(item=1)", "(1,).index(item=1)", "(1,).count(item=1)",
    "(1,).__contains__(item=1)",
    *[f"{value}.{method}(other={value})" for value in ("[1]", "(1,)", "{1: 1}")
      for method in ("__eq__", "__ne__")],
    *[f"{{1}}.{method}(other={{1}})" for method in (
        "__eq__", "__ne__", "__le__", "__lt__", "__ge__", "__gt__",
    )],
])
def test_js_collection_comparison_hooks_reject_keyword_operands(expression):
    with pytest.raises(TypeError):
        eval(expression)
    with pytest.raises(CompilationError, match="positional-only") as caught:
        analyze_module_source(f"def main() -> str:\n    return str({expression})\n")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("analyze", [transpile_llvm, analyze_module_source])
@pytest.mark.parametrize("expression", [
    *[f"{{1: 2}}.{method}(key=1)" for method in (
        "get", "pop", "setdefault", "__getitem__", "__contains__", "__delitem__",
    )],
    *[f"{{1: 2}}.{method}(1, default=3)" for method in (
        "get", "pop", "setdefault",
    )],
    "{1: 2}.__setitem__(1, value=3)",
    "[1].pop(index=0)", "[1].insert(index=0, item=2)",
])
def test_collection_lookup_and_mutation_keywords_are_positional_only(analyze, expression):
    with pytest.raises(TypeError):
        eval(expression)
    with pytest.raises(CompilationError, match="positional-only") as caught:
        analyze(f"def main() -> str:\n    return str({expression})\n")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("analyze", [transpile_llvm, analyze_module_source])
@pytest.mark.parametrize("method", ["get", "pop", "setdefault", "__contains__", "__delitem__"])
def test_mapping_hooks_validate_missing_keys(analyze, method):
    expression = f"{{1: 2}}.{method}()"
    with pytest.raises(TypeError):
        eval(expression)
    with pytest.raises(CompilationError, match="missing required argument") as caught:
        analyze(f"def main() -> str:\n    return str({expression})\n")
    assert caught.value.lineno == 2


def test_variadic_tuple_return_accepts_fixed_tuple_views():
    LLVM().assert_matches_python('''
            def values() -> tuple[int, ...]:
                result = (1, 2, 3)
                return result

            def main() -> int:
                return len(values())
        ''')


@pytest.mark.parametrize("expression, message", [
    ("min(1, 2.5)", "extrema arguments require matching result storage"),
    ("max(1.5, 2)", "extrema arguments require matching result storage"),
    ("max(count, 0.0)", "extrema arguments require matching result storage"),
    ("min(True, 2)", "extrema arguments require matching result storage"),
    ("min([1], default=2.5)", "extrema require matching result types"),
])
def test_mixed_extrema_report_a_located_boundary(expression, message):
    with pytest.raises(LLVMUnsupported, match=message + ".*at line"):
        transpile_llvm(f"def main() -> str:\n    count = 3\n    return str({expression})\n")


def test_unorderable_extrema_fail_in_shared_analysis():
    with pytest.raises(CompilationError, match="min.*cannot order values of type int, str"):
        transpile_llvm("def main() -> str:\n    return str(min('a', 1))\n")


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["min", "max"])
def test_union_item_ordering_preserves_selected_type(tmp_path, optimize, operation):
    comparison = LLVM().assert_matches_python(f'''
            def consume(values: list[int | float]) -> str:
                return str({operation}(values))

            def main() -> str:
                return consume([1, 2.5]) + ":" + consume([1.0, 1])
        ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_pop_key_errors_match_python_messages(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            errors: list[str] = []
            values: set[int] = set()
            mapping: dict[str, int] = dict()
            try:
                values.pop()
            except KeyError as first:
                errors.append(str(first))
            try:
                mapping.popitem()
            except KeyError as second:
                errors.append(str(second))
            return "|".join(errors)
    ''', optimize=optimize)
