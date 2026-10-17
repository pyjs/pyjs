import textwrap

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    LAZY_ITERATOR_CONTRACT,
    MAPPING_VIEW_REPRESENTATION_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_mapping_view_representation_contract(optimize):
    result = LLVM().assert_matches_python(MAPPING_VIEW_REPRESENTATION_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, MAPPING_VIEW_REPRESENTATION_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_lazy_iterator_contract(optimize):
    result = LLVM().assert_matches_python(LAZY_ITERATOR_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, LAZY_ITERATOR_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [
    '''
    from collections.abc import Iterator

    def make() -> Iterator[int]:
        return iter([3, 4, 5])

    def consume(values: Iterator[int]) -> int:
        return next(values)

    def main() -> str:
        values = make()
        alias = iter(values)
        result = str(alias is values) + str(bool(values))
        result += str(consume(alias))
        for value in values:
            result += str(value)
        result += str(next(alias, 7)) + str(bool(values))
        try:
            next(values)
        except StopIteration as error:
            result += "empty:" + str(error)
        result += str(next(values, 8))
        values = [1, 2].__iter__()
        return result + str(values.__iter__() is values) + str(values.__next__())
    ''',
    '''
    def main() -> str:
        result = ""
        for value in iter((1, 2, 3)):
            result += str(value)
        for value in reversed((1, 2, 3)):
            result += str(value)
        for character in iter("aé😀\\x00"):
            result += character + ":"
        for character in reversed("aé😀\\x00"):
            result += character + ":"
        for value in iter(b"a\\x00\\xff"):
            result += str(value) + ","
        for value in reversed(b"a\\x00\\xff"):
            result += str(value) + ","
        for value in iter(range(-5, 9, 3)):
            result += str(value)
        for value in reversed(range(9, -5, -3)):
            result += str(value)
        return result
    ''',
    '''
    def main() -> str:
        values = [1, 2, 3]
        forward = iter(values)
        backward = reversed(values)
        result = str(next(forward)) + str(next(backward))
        values[1] = 7
        values.append(4)
        result += str(list(forward) == [7, 3, 4])
        result += str(list(backward) == [7, 1])
        values.append(5)
        result += str(next(forward, -1)) + str(next(backward, -1))
        values.clear()
        backward = reversed(values)
        values.append(9)
        return result + str(next(backward, -1))
    ''',
    '''
    def main() -> str:
        mapping = {"a": 1, "b": 2}
        keys = iter(mapping)
        values = iter(mapping.values())
        items = iter(mapping.items())
        reverse = reversed(mapping.items())
        mapping["a"] = 8
        result = next(keys) + str(next(values))
        for key, value in items:
            result += key + str(value)
        for key, value in reverse:
            result += key + str(value)
        result += str(set(iter({3, 5})) == {3, 5})
        mapping["c"] = 3
        try:
            next(keys)
        except RuntimeError:
            result += "mutated"
        mapping.pop("c")
        try:
            next(keys)
        except RuntimeError:
            result += "sticky"
        return result
    ''',
    '''
    def main() -> str:
        values = iter([4, 2, 3])
        indexed = enumerate(values, start=-2)
        result = ""
        for index, value in indexed:
            result += str(index) + ":" + str(value) + ";"
        result += str(next(values, 9))
        rows = zip([1, 2], ["a", "b"], [True, False], strict=True)
        for index, text, flag in rows:
            result += str(index) + text + str(flag)
        left = iter([2, 4, 6])
        for a, b in zip(left, left):
            result += str(a) + str(b)
        result += str(next(left, 8))
        pairs = zip(["a", "b"], [5, 6])
        result += str(dict(pairs) == {"a": 5, "b": 6})
        for index, pair in enumerate(zip([1, 2], [3, 4])):
            result += str(index) + str(pair[0]) + str(pair[1])
        return result
    ''',
    '''
    def main() -> str:
        values = iter([0, 2, 3])
        result = str(any(values)) + str(next(values))
        values = iter([1, 0, 3])
        result += str(all(values)) + str(next(values))
        result += str(sum(iter([2, 3, 4])))
        result += str(sum(iter([1e16, 1.0, -1e16]), 0.0))
        result += str(min(iter([4, -1, 3]))) + str(max(iter([4, -1, 3])))
        result += str(sorted(iter([4, -1, 3])) == [-1, 3, 4])
        extended = [8]
        extended.extend(iter([2, 3]))
        result += str(extended == [8, 2, 3])
        members = {1, 2}
        members.update(iter([2, 3]))
        result += str(members == {1, 2, 3})
        result += str(members.intersection(iter([2, 3, 4])) == {2, 3})
        return result
    ''',
], ids=["identity-and-exhaustion", "concrete-sources", "live-lists", "mapping-views", "adapters", "consumers"])
def test_lazy_iterator_scenarios(source, optimize):
    LLVM().assert_matches_python(source, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_strict_zip_consumption_and_nested_errors(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            first = iter([1, 2, 3])
            second = iter([4])
            pairs = zip(first, second, strict=True)
            result = ""
            try:
                for a, b in pairs:
                    result += str(a) + str(b)
            except ValueError as error:
                result += str(error)
            result += str(next(first, 9))
            try:
                next(pairs)
            except StopIteration:
                result += "done"
            second = iter([4, 5, 6])
            pairs = zip([1], second, strict=True)
            try:
                list(pairs)
            except ValueError as error:
                result += str(error)
            result += str(next(second))
            try:
                list(enumerate(zip([1], [2], [3, 4], strict=True)))
            except ValueError as error:
                result += str(error)
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_roots_and_materialized_rows_survive_collection(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def make(seed: int) -> Iterator[tuple[int, tuple[str, str]]]:
            return enumerate(zip(["a" + str(seed), "b" + str(seed)],
                                 ["c" + str(seed), "d" + str(seed)]))

        def main() -> str:
            gc_set_threshold(1)
            values = make(7)
            gc_collect()
            first = next(values)
            gc_collect()
            result = ""
            for index, pair in values:
                gc_collect()
                result += str(index) + pair[0] + pair[1]
            gc_collect()
            return result + str(first[0]) + first[1][0] + first[1][1]
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_control_flow(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            result = ""
            values = iter([1, 2, 3, 4])
            for value in values:
                if value == 1:
                    continue
                if value == 3:
                    break
            else:
                result += "wrong"
            result += str(next(values))
            for value in values:
                result += "wrong"
            else:
                result += "done"
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_argument_evaluation_and_default_eagerness(optimize):
    LLVM().assert_matches_python('''
        def value(events: list[int], number: int) -> int:
            events.append(number)
            return number

        def items(events: list[int], number: int) -> list[int]:
            events.append(number)
            return [number]

        def main() -> str:
            events: list[int] = []
            rows = enumerate(start=value(events, 7), iterable=items(events, 3))
            result = str(events == [7, 3]) + str(next(rows) == (7, 3))
            values = iter(items(events, 4))
            result += str(next(values, value(events, 9)))
            result += str(events == [7, 3, 4, 9])
            result += str(list(enumerate([5], True)) == [(1, 5)])
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_text_consumers_stop_at_the_right_boundary(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            words = iter(["a", "é", "😀"])
            result = "|".join(words) + str(next(words, "done"))
            result += ":".join(("a", "b")) + "-".join("aé😀")
            parts = iter([b"a", b"\\x00", b"\\xff"])
            result += b"|".join(parts).hex() + next(parts, b"done").decode()
            values = iter([0, 255, 65])
            result += bytes(values).hex() + str(next(values, 9))
            invalid = iter([1, 256, 7])
            try:
                bytes(invalid)
            except ValueError as error:
                result += str(error)
            result += str(next(invalid))
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterators_preserve_portable_items_and_application_object_identity(optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        def main() -> str:
            gc_set_threshold(1)
            small = iter([int8(127), int8(-3)])
            result = str(next(small) + int8(1)) + str(next(small))
            wide = iter([int64(9007199254740993)])
            result += str(next(wide) + int64(2))
            floats = iter([float32(16777216.0)])
            result += str(next(floats) + float32(1.0))
            for index, value in enumerate([int8(127)]):
                result += str(value + int8(1)) + str(index)
            for floating, other in zip([float32(16777216.0)], [float32(1.0)]):
                result += str(floating + other)
            box = Box(3)
            objects = iter([box])
            gc_collect()
            item = next(objects)
            result += str(item is box)
            item.value = 8
            gc_collect()
            return result + str(box.value)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_row_collections_compare_by_value(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            left = list(enumerate(zip([1, 2], ["a", "b"])))
            equal = [(0, (1, "a")), (1, (2, "b"))]
            unequal = [(0, (1, "a")), (1, (3, "b"))]
            result = str(left == equal) + str(left != unequal)
            result += str(left == left) + str(left == [])
            result += str(left[:1] == equal[:1])
            result += str([[1], [2]] == [[1], [2]])
            result += str([[1]] != [[2]]) + str([[1]] != [[1], [2]])
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_sources_and_single_source_zip(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            result = ""
            for unused in iter(()):
                result += "wrong"
            for unused in zip():
                result += "wrong"
            empty: list[str] = []
            result += "|".join(iter(empty))
            result += str(next(iter(empty), "done"))
            result += str(list(zip([1, 2])) == [(1,), (2,)])
            result += str(list(enumerate([3], 9223372036854775807)) == [(9223372036854775807, 3)])
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_membership_consumes_through_match_and_preserves_operand_order(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator

        def needle(events: list[str]) -> int:
            events.append("needle")
            return 2

        def values(events: list[str]) -> Iterator[int]:
            events.append("values")
            return iter([1, 2, 3])

        def main() -> str:
            events: list[str] = []
            result = str(needle(events) in values(events))
            result += "|".join(events)
            cursor = iter([1, 2, 3, 4])
            result += str(2 in cursor) + str(next(cursor))
            result += str(9 not in cursor) + str(next(cursor, -1))
            pairs = zip([1, 2, 3], ["a", "b", "c"])
            result += str((2, "b") in pairs) + next(pairs)[1]
            empty: list[int] = []
            result += str(any([iter(empty)])) + str(all([iter(empty)]))
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_fields_and_aliases_remain_rooted(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Stream:
            def __init__(self, values: Iterator[str]):
                self.values = values

            def take(self) -> str:
                return next(self.values, "done")

        def make(index: int) -> Stream:
            return Stream(iter(["a" + str(index), "b" + str(index)]))

        def main() -> str:
            gc_set_threshold(1)
            streams = [make(7)]
            gc_collect()
            alias = streams[0].values
            result = streams[0].take()
            streams.clear()
            gc_collect()
            result += next(alias)
            gc_collect()
            return result + next(alias, "done")
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_temporary_sources_survive_later_collecting_arguments(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        def source(events: list[int], value: int) -> list[Box]:
            events.append(value)
            gc_collect()
            return [Box(value), Box(value + 1)]

        def strict(events: list[int]) -> bool:
            events.append(9)
            gc_collect()
            return True

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            rows = zip(source(events, 1), source(events, 3), strict=strict(events))
            result = str(events == [1, 3, 9])
            for left, right in rows:
                gc_collect()
                result += str(left.value) + str(right.value)
            for index, value in enumerate(reversed(source(events, 5))):
                gc_collect()
                result += str(index) + str(value.value)
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_strict_zip_mismatch_repeated_calls_and_exception_cleanup(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            rows = zip([1, 2, 3], [4], strict=True)
            result = ""
            for attempt in range(4):
                try:
                    row = next(rows)
                    result += str(row[0]) + str(row[1])
                except ValueError as error:
                    result += str(error)
                except StopIteration:
                    result += "done"
                finally:
                    result += ";"
            try:
                for index, row in enumerate(zip([1], [2, 3], strict=True)):
                    result += str(index) + str(row[1])
            except ValueError as error:
                result += str(error)
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source, line, message", [
    ("def main() -> int:\n    values = iter(range(0))\n    return next(values)\n", 3, "StopIteration: "),
    ("def main() -> int:\n    for left, right in zip([1, 2], [3], strict=True):\n        pass\n    return 0\n",
     2, "ValueError: zip() argument 2 is shorter than argument 1"),
])
def test_iterator_errors_have_python_source_tracebacks(source, line, message, optimize):
    execution = LLVM().run_source(source, filename="cursor.py", optimize=optimize)
    assert execution.returncode < 0
    assert execution.stderr == (
        "Traceback (native PyJS):\n"
        f'  File "cursor.py", line {line}, in main\n'
        f"{message}\n"
    )


@pytest.mark.parametrize("body, message", [
    ("return list(iter((1, 'a')))", "homogeneous"),
])
def test_iterator_unsupported_boundaries(body, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm("def main():\n" + textwrap.indent(body, "    "))
