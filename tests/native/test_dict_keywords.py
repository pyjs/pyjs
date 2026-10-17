import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_keywords_merge_in_order_and_infer_union_values(optimize):
    result = LLVM().assert_matches_python('''
        def main() -> str:
            base = {"first": 1, "same": 2}
            merged = dict(base, same=5, **{"last": 4}, tail=6)
            mixed = dict(name="Ada", count=2)
            widened = dict(base, word="value")
            return repr((merged, mixed, widened, dict(other=7, fields=8)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_pair_sources_contribute_scalar_and_pointer_union_arms(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        def pairs() -> Iterator[tuple[str, int]]:
            gc_collect()
            yield ("a", 1)
        def main() -> str:
            gc_set_threshold(1)
            fields = {"b": "word"}
            direct = dict([("a", [1, 2])], b="word")
            packed = dict([("a", [1, 2])], **fields)
            mixed = dict([("a", 1)], b="word")
            floats = dict([("a", 1)], b=2.5)
            nullable = dict([("a", 1)], b=None)
            reversed = dict([("a", "word")], **{"b": 1})
            view = dict({"a": 1}.items(), b="word")
            generated = dict(pairs(), b="word")
            gc_collect()
            return repr((isinstance(direct["a"], list), isinstance(direct["b"], str),
                         isinstance(packed["a"], list), isinstance(packed["b"], str),
                         direct, packed, mixed, floats, nullable, reversed, view, generated))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_keyword_keys_accept_real_builtin_aliases(optimize):
    result = LLVM().assert_matches_python('''
        from builtins import dict as Mapping, str as Text
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            fields = {Text(3): [4]}
            result = Mapping(**fields, extra=[5])
            gc_collect()
            return repr(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_heterogeneous_pair_tuples_preserve_every_value_arm(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            source = (("a", [1, 2]), ("b", "word"))
            direct = dict(source, c="tail")
            fields = {"c": "tail"}
            packed = dict(source, **fields)
            bare = dict(source)
            numeric = dict((("a", 1), ("b", "word")), c="tail")
            represented = dict((("a", int8(127)), ("b", "word")), c="tail")
            scalar = represented["a"]
            if not isinstance(scalar, int):
                return "wrong scalar tag"
            gc_collect()
            return repr((isinstance(direct["a"], list), isinstance(direct["b"], str),
                         isinstance(packed["a"], list), isinstance(bare["b"], str),
                         direct, packed, bare, numeric, int(scalar + int8(1))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("fields", ['b="word"', 'b=[2]', '**{"b": [2]}'])
def test_typeddict_keyword_source_has_a_located_boundary(fields):
    with pytest.raises(CompilationError, match="construction from TypedDict is not implemented") as caught:
        transpile_llvm(f'''
            from typing import TypedDict
            class Row(TypedDict):
                a: list[int]
            def main() -> int:
                row: Row = {{"a": [1]}}
                return len(dict(row, {fields}))
        ''', filename="dict_source.py")
    assert caught.value.filename == "dict_source.py"
    assert caught.value.lineno == 7


def test_dictionary_keyword_keys_reject_application_string_namesakes():
    with pytest.raises(CompilationError, match="concrete string-keyed dict") as caught:
        transpile_llvm('''
            class str:
                def __hash__(self) -> int: return 7
                def __eq__(self, other: str) -> bool: return self is other
            def main() -> int:
                fields = {str(): 1}
                return len(dict(**fields))
        ''', filename="dict_namesake.py")
    assert caught.value.filename == "dict_namesake.py"
    assert caught.value.lineno == 7


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_keywords_evaluate_before_source_consumption_and_survive_gc(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        def value(label: str) -> str:
            gc_collect()
            return label + "-kept"
        def change(base: dict[str, int], events: list[str]) -> int:
            events.append("keyword")
            base["first"] = 9
            gc_collect()
            return 7
        def pairs(events: list[str]) -> Iterator[tuple[str, int]]:
            events.append("consume")
            yield ("first", 1)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            base = {"first": 1}
            copied = dict(base, last=change(base, events))
            consumed = dict(pairs(events), last=change(base, events))
            kept = dict(first=value("one"), second=value("two"))
            return repr((copied, consumed, kept, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_dynamic_keywords_reject_duplicates_and_recover(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def later(events: list[str]) -> int:
            events.append("later")
            gc_collect()
            return 8
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            fields = {"first": 2}
            result = dict(**fields)
            try:
                result = dict(first=1, **fields, tail=later(events))
            except TypeError:
                events.append("duplicate")
            fields.clear()
            return repr((result, dict(first=1, **fields, tail=later(events)), events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_keyword_packs_snapshot_before_later_mutation(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def change(fields: dict[str, str]) -> str:
            fields.clear()
            gc_collect()
            return "last"
        def main() -> str:
            gc_set_threshold(1)
            fields = {"first": "kept" + str(3)}
            result = dict(**fields, tail=change(fields))
            return repr((result, fields))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_keywords_preserve_portable_value_storage(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        def main() -> str:
            small = dict(first=int8(127), second=int8(1))
            rounded = dict(first=float32(16777217.0), second=float32(2.5))
            fields = {"third": int8(2)}
            expanded = dict(first=int8(3), **fields)
            from_pairs = dict([("first", [int8(127)])], second="word")
            first = from_pairs["first"]
            if not isinstance(first, list):
                return "wrong pair value tag"
            scalar_pairs = dict([("first", int8(127))], second="word")
            scalar = scalar_pairs["first"]
            if not isinstance(scalar, int):
                return "wrong scalar pair tag"
            return repr((int(small["first"] + small["second"]),
                         float(rounded["first"]), int(expanded["third"]),
                         int(first[0] + int8(1)), int(scalar + int8(1))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_keyword_merge_errors_preserve_effect_order_and_result_identity(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        def mark(events: list[int], value: int) -> int:
            events.append(value)
            gc_collect()
            return value
        def pairs(events: list[int]) -> Iterator[tuple[str, int]]:
            events.append(8)
            yield ("saved", 9)
            raise ValueError("broken source")
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            source = {"key": 1}
            copy = dict(**source)
            copy["key"] = 9
            try:
                dict(**{"key": mark(events, 1), "key": mark(events, 2)},
                     **{"key": mark(events, 3)}, tail=mark(events, 4))
            except TypeError:
                events.append(5)
            try:
                dict(pairs(events), last=mark(events, 6))
            except ValueError:
                events.append(7)
            return repr((source, copy, events, dict(**source)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("fields", ['{1: 2}', '{"one": 1, 2: 2}', '[("one", 1)]'])
def test_dynamic_keyword_mapping_requires_string_keys(fields):
    with pytest.raises(CompilationError, match="concrete string-keyed dict") as caught:
        transpile_llvm(f'''
def main() -> int:
    fields = {fields}
    return len(dict(**fields))
''', filename="dict_boundary.py")
    assert caught.value.filename == "dict_boundary.py"
    assert caught.value.lineno == 4


@pytest.mark.parametrize("expression, message", [
    ('dict(*[{"a": 1}], b=2)', "unsupported LLVM expression Starred"),
    ('dict({1: 2}, b=3)', "dictionary update requires matching key layouts"),
])
def test_dictionary_keyword_constructor_keeps_typed_source_boundaries(expression, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f"def main() -> int:\n    return len({expression})\n")


@pytest.mark.parametrize("fields", ['b=int16(2)', '**{"b": int16(2)}'])
def test_dictionary_keywords_reject_incompatible_portable_widths(fields):
    with pytest.raises(CompilationError, match="incompatible nested representations"):
        transpile_llvm(f'''
            from pyjs import int8, int16
            def main() -> int:
                return len(dict(a=int8(1), {fields}))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_keyword_allocation_failures_preserve_destination_and_retry(tmp_path, optimize):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm
        def main() -> int:
            gc_set_threshold(1)
            base = {"first": "one"}
            fields = {"second": "two"}
            failures = 0
            for cutoff in range(1, 40):
                result = {"sentinel": "old"}
                previous = result
                caught = False
                arm(cutoff)
                try:
                    result = dict(base, **fields, third="three")
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if caught:
                    failures += 1
                    if result is not previous or result != {"sentinel": "old"}: return 1
                elif result != {"first": "one", "second": "two", "third": "three"}:
                    return 2
                if dict(base, **fields, third="three") != {"first": "one", "second": "two", "third": "three"}:
                    return 3
                if base != {"first": "one"} or fields != {"second": "two"}: return 4
            return 0 if failures else 5
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
