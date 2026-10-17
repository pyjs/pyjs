from pyjs.testing.helpers import at

from .helpers import assert_semantics


def test_empty_list_extend_and_slice_replacement_keep_destination_values():
    assert_semantics('''
        values = [1, 2, 3]
        alias = values
        values.extend([])
        values[1:] = []
        print(len(values), values[0], alias is values)
    ''')


def test_list_and_tuple_repetition_matches_python():
    assert_semantics(
        """\
        values = [1, 2]
        print(len(values * 3), len(3 * values))
        print(len(values * 0), len(values * -2))

        coordinates = (1, 2)
        print(len(coordinates * 2), len(2 * coordinates))
        print(len(coordinates * 0), len(coordinates * -1))

        nested = [[1]]
        repeated = nested * 2
        nested[0].append(2)
        print(repeated[0][1], repeated[1][1])
        """
    )


def test_boolean_operators_use_python_collection_truthiness_once():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def record(events: list[str], name: str, value: list[int]) -> list[int]:
            events.append(name)
            return value

        events: list[str] = []
        selected: list[int] | str = record(events, "empty", []) or "fallback"
        print(isinstance(selected, str), len(events), events[0])

        events.clear()
        retained: list[int] | str = record(events, "full", [1]) or "fallback"
        print(isinstance(retained, list), len(events), events[0])

        events.clear()
        stopped: list[int] | str = record(events, "empty", []) and "unused"
        print(isinstance(stopped, list), len(events), events[0])

        events.clear()
        continued: list[int] | str = record(events, "full", [1]) and "used"
        print(isinstance(continued, str), len(events), events[0])
        """
    )


def test_boolean_operators_cover_dynamic_and_builtin_truthiness():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Choice:
            def __init__(self, enabled: bool):
                self.enabled = enabled

            def __bool__(self) -> bool:
                return self.enabled

        print(isinstance([] or "list", str))
        print(isinstance({} or "dict", str))
        print(isinstance(set[int]() or "set", str))
        print(isinstance(() or "tuple", str))
        print((float("nan") or 1.0) != 1.0)
        print(isinstance(Choice(False) or "choice", str))
        print(isinstance(Choice(True) and "choice", str))
        """
    )


def test_starred_expansion_uses_union_and_custom_iterable_item_types():
    assert_semantics(
        """\
        from collections.abc import Iterator

        from pyjs import js

        @js
        def values() -> list[int | str]:
            return [1, "two"]

        @js
        class Numbers:
            def __iter__(self) -> Iterator[int]:
                return iter([3, 4])

        expanded: list[int | str] = [0, *values(), *Numbers()]
        for value in expanded:
            print(value)
        """
    )


def test_dictionary_unpacking_matches_python_overwrite_order():
    assert_semantics(
        """\
        first = {"a": 1, "shared": 2}
        second = {"b": 3, "shared": 4}
        merged = {"start": 0, **first, **second, "shared": 5}
        print(merged["start"], merged["a"], merged["b"], merged["shared"])
        """
    )


def test_callable_instances_match_python_dispatch():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Add:
            def __call__(self, value: int) -> int:
                return value + 1

        @js
        class Double(Add):
            def __call__(self, value: int) -> int:
                return value * 2

        add = Add()
        print(add(2), Add()(3), Double()(4))
        """
    )


def test_list_and_tuple_membership_use_python_equality():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Match:
            def __init__(self, key: str):
                self.key = key

            def __eq__(self, other: Match) -> bool:
                return self.key == other.key

        pair = [1, 2]
        values = ([1, 2], [3, 4])
        print(pair in values, [4, 5] not in values)
        print(pair in [[1, 2], [3, 4]], [4, 5] not in [[1, 2], [3, 4]])
        print(2 in (1, 2, 3), 4 not in (1, 2, 3))
        print(Match("first") in (Match("first"), Match("second")))
        print(Match("missing") not in (Match("first"), Match("second")))
        print(Match("first") in [Match("first"), Match("second")])
        print(Match("missing") not in [Match("first"), Match("second")])
        """
    )


def test_empty_collection_comparisons_use_structural_equality():
    assert_semantics(
        """\
        values: list[int] = []
        print(values == [], [] == values, values != [])
        pair: tuple[int, ...] = ()
        print(pair == (), () == pair, pair != ())
        mapping: dict[str, int] = {}
        print(mapping == {}, {} == mapping, mapping != {})
        mapping["value"] = 1
        print(mapping == {"value": 1}, mapping != {"value": 2})
        """
    )


def test_split_matches_separator_whitespace_and_maxsplit_semantics():
    assert_semantics(
        """\
        value = "one,two,three"
        print(repr(value.split(",")))
        print(repr(value.split(",", 0)))
        print(repr(value.split(",", 1)))
        print(repr(value.split(",", -2)))
        print(repr(value.split("missing", 1)))
        print(repr(value.split(sep=",", maxsplit=1)))

        whitespace = "  one\t two   three  "
        print(repr(whitespace.split()))
        print(repr(whitespace.split(None)))
        print(repr(whitespace.split(None, 0)))
        print(repr(whitespace.split(None, 1)))
        print(repr(whitespace.split(maxsplit=2)))
        print(repr("   ".split(None, 0)))
        print(len("one\\x1ctwo".split()))
        print(len("\\ufeffone".split()))

        separator = ""
        try:
            value.split(separator)
        except ValueError as error:
            print(str(error))
        """
    )


def test_list_pop_accepts_an_index_and_negative_indexes_read_from_the_end():
    assert_semantics(
        """\
        values = ["zero", "one", "two"]
        print(values.pop(1))
        print(values[-1])
        print("last"[-1])
        print(len(values))
        """
    )


def test_list_pop_rejects_indexes_outside_the_list():
    assert_semantics(
        """\
        values = ["zero", "one"]
        print(values.pop())
        print(values.pop(-1))
        try:
            values.pop()
        except Exception:
            print("empty")

        values = ["zero", "one"]
        try:
            values.pop(2)
        except Exception:
            print("high", len(values))
        try:
            values.pop(-3)
        except Exception:
            print("low", len(values))
        """
    )


def test_sequence_item_access_and_list_assignment_raise_index_error():
    assert_semantics(
        """\
        values = ["zero", "one"]
        values[-1] = "last"
        print(values[1])
        values[True] = "boolean"
        print(values[True])

        for index in (-3, 2):
            try:
                print(values[index])
            except IndexError as error:
                print(str(error))
            try:
                values[index] = "missing"
            except IndexError as error:
                print(str(error))

        for text, index in (("value", -6), ("value", 5)):
            try:
                print(text[index])
            except IndexError as error:
                print(str(error))

        emoji = "A😀B"
        print(emoji[1], emoji[-2])

        pair = ("left", 2)
        print(pair[-2], pair[1])
        for index in (-3, 2):
            try:
                print(pair[index])
            except IndexError as error:
                print(str(error))

        empty = ()
        try:
            print(empty[0])
        except IndexError as error:
            print(str(error))
        """
    )


def test_mapping_and_set_mutations_raise_key_error_without_changing_values():
    assert_semantics(
        """\
        values = {"one": 1}
        print(values.pop("one"), len(values))
        try:
            values.pop("missing")
        except KeyError as error:
            print(str(error), len(values))

        names = {"Ada", "Grace"}
        names.remove("Ada")
        print("Ada" in names, "Grace" in names)
        try:
            names.remove("missing")
        except KeyError as error:
            print(str(error), len(names))

        selected = names.pop()
        print(selected, len(names))
        try:
            names.pop()
        except KeyError as error:
            print(str(error), len(names))
        """
    )


def test_dict_setdefault_preserves_existing_values_and_default_identity():
    assert_semantics(
        """\
        values: dict[str, list[int]] = {}
        fallback = [1]
        first = values.setdefault("items", fallback)
        second = values.setdefault("items", [2])
        first.append(3)
        print(first is fallback)
        print(first is second)
        print(len(values), len(second), second[0], second[1])
        """
    )


def test_dict_setdefault_without_a_default_inserts_none():
    assert_semantics(
        """\
        values: dict[str, int] = {"present": 4}
        present = values.setdefault("present")
        missing = values.setdefault("missing")
        print(present, missing is None)
        print(len(values), values["missing"] is None)
        """
    )


def test_dict_optional_get_and_pop_defaults_match_python():
    assert_semantics(
        """\
        values: dict[str, int] = {"present": 4}
        present = values.get("present")
        missing = values.get("missing")
        print(present)
        print("none" if missing is None else "value")
        print(values.pop("missing", 7), len(values))
        optional = values.pop("absent", None)
        print("none" if optional is None else "value", len(values))
        print(values.pop("present"), len(values))
        try:
            values.pop("missing")
        except KeyError as error:
            print(str(error), len(values))

        collections: dict[str, list[int]] = {}
        fallback: list[int] = []
        print(collections.get("missing", fallback) is fallback)
        print(collections.pop("missing", fallback) is fallback)
        """
    )


def test_list_and_dict_copies_are_shallow_and_dict_update_mutates_in_place():
    assert_semantics(
        """\
        nested = [1]
        values = [nested]
        copied_values = values.copy()
        copied_values.append([2])
        print(nested is copied_values[0], len(values), len(copied_values))

        mapping = {"one": 1}
        copied_mapping = mapping.copy()
        result = mapping.update({"one": 2, "two": 3})
        copied_mapping["three"] = 4
        print(mapping["one"], mapping["two"], len(mapping))
        print(copied_mapping["one"], len(copied_mapping), result is None)
        """
    )


def test_dict_update_accepts_empty_and_keyword_calls():
    assert_semantics(
        """\
        values: dict[str, int] = {"one": 1}
        empty_result = values.update()
        mixed_result = values.update({"two": 2}, three=3)
        keyword_result = values.update(values=4)
        print(empty_result is None, mixed_result is None, keyword_result is None)
        print(values == {"one": 1, "two": 2, "three": 3, "values": 4})
        """
    )


def test_dict_update_accepts_iterable_pairs():
    assert_semantics(
        """\
        values: dict[str, int] = {"one": 1}
        values.update([("two", 2), ("one", 3)])
        values.update((key, len(key)) for key in ["three", "four"])
        print(values == {"one": 3, "two": 2, "three": 5, "four": 4})
        """
    )


def test_dict_popitem_uses_lifo_order_and_rejects_empty_mappings():
    assert_semantics(
        """\
        values = {"first": 1, "second": 2}
        values["first"] = 3
        pair = values.popitem()
        print(pair[0], pair[1])
        del values["first"]
        values["first"] = 4
        pair = values.popitem()
        print(pair[0], pair[1])
        print(len(values))
        try:
            values.popitem()
        except KeyError as error:
            print(str(error))
        """
    )


def test_string_ordering_uses_unicode_code_points():
    assert_semantics(
        """\
        print("alpha" < "beta")
        print("beta" <= "beta")
        print("beta" > "alpha")
        print("beta" >= "beta")
        print("\ue000" < "😀")
        print("😀" > "\ue000")
        """
    )


def test_list_and_dict_mutations_return_none_and_extend_iterables():
    assert_semantics(
        """\
        values: list[int] = []
        print(values.append(1) is None)
        print(values.extend((2, 3)) is None)
        print(values.insert(-100, 0) is None)
        print(values.insert(100, 4) is None)
        print(repr(values))

        names: list[str] = []
        mapping = {"first": 1, "second": 2}
        print(names.extend(mapping) is None)
        names.extend("ok")
        print(repr(names))

        assigned: dict[str, int] = {}
        print(assigned.__setitem__("answer", 42) is None)
        print(assigned["answer"])

        from typing import TypedDict

        class Record(TypedDict):
            answer: int

        record = Record(answer=1)
        print(record.__setitem__("answer", 42) is None)
        print(record["answer"])
        """
    )


def test_list_mutation_lowering_preserves_none_and_python_iteration():
    at(
        """\
        def main():
            values: list[int] = []
            append_result = values.append(1)
            extend_result = values.extend((2, 3))
            insert_result = values.insert(1, 4)
            names: list[str] = []
            mapping = {"first": 1, "second": 2}
            names.extend(mapping)
            assigned: dict[str, int] = {}
            set_result = assigned.__setitem__("answer", 42)
        """,
        """
        def main() -> None:
            values: list[int] = []
            append_result: None = values.[list__int]append!(1)
            extend_result: None = values.[list__int]extend!((2, 3))
            insert_result: None = values.[list__int]insert!(1, 4)
            names: list[str] = []
            mapping: dict[str, int] = {'first': 1, 'second': 2}
            names.[list__str]extend!(mapping)
            assigned: dict[str, int] = {}
            set_result: None = assigned.[dict__str_int]__setitem__!('answer', 42)
        """,
        """
        export function main() {
            var values = [];
            var append_result = (values.push(1), null);
            var extend_result = (values.push(...[2, 3]), null);
            var insert_result = (values.splice(1, 0, 4), null);
            var names = [];
            var mapping = new Map([['first', 1], ['second', 2]]);
            (names.push(...mapping.keys()), null);
            var assigned = new Map([]);
            var set_result = (assigned.set('answer', 42), null);
        }
        """,
    )


def test_sequence_count_and_list_reverse_match_python_equality():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Match:
            def __init__(self, key: str):
                self.key = key

            def __eq__(self, other: Match) -> bool:
                return self.key == other.key

        numbers = [1, True, 2, 1]
        print(numbers.count(1), numbers.count(3))
        nested = [[1], [2], [1]]
        print(nested.count([1]))
        matches = [Match("same"), Match("other"), Match("same")]
        print(matches.count(Match("same")))
        coordinates = (Match("same"), Match("other"), Match("same"))
        print(coordinates.count(Match("same")))
        print(numbers.reverse() is None, repr(numbers))
        """
    )


def test_sequence_count_and_list_reverse_have_explicit_lowering():
    at(
        """\
        def main():
            values = [1, 2, 1]
            matches = values.count(1)
            reverse_result = values.reverse()
            coordinates = (1, 2, 1)
            tuple_matches = coordinates.count(1)
        """,
        """
        def main() -> None:
            values: list[int] = [1, 2, 1]
            matches: int = $count_equal_sequence_items(values, 1)
            reverse_result: None = values.[list__int]reverse!()
            coordinates: tuple[int, int, int] = (1, 2, 1)
            tuple_matches: int = $count_equal_sequence_items(coordinates, 1)
        """,
        """
        import { count_equal_sequence_items as $count_equal_sequence_items } from './pyjs.python.js';

        export function main() {
            var values = [1, 2, 1];
            var matches = $count_equal_sequence_items(values, 1);
            var reverse_result = (values.reverse(), null);
            var coordinates = [1, 2, 1];
            var tuple_matches = $count_equal_sequence_items(coordinates, 1);
        }
        """,
    )


def test_list_equality_compares_nested_values():
    assert_semantics(
        """\
        left = [1, [2, 3]]
        print(left == [1, [2, 3]])
        print(left != [1, [2, 4]])
        """
    )


def test_explicit_bool_uses_python_container_truthiness():
    assert_semantics(
        """\
        print(bool())
        print(bool([]), bool([0]))
        print(bool({}), bool({"answer": 42}))
        print(bool(()), bool((0,)))
        print(bool(""), bool("value"))
        """
    )


def test_list_and_string_slices_preserve_python_bounds_and_steps():
    assert_semantics(
        """\
        values = [0, 1, 2, 3, 4, 5]
        print(repr(values[:]))
        print(repr(values[::-1]))
        print(repr(values[4:0:-2]))
        print(repr(values[-2::-2]))
        print(repr(values[:-1:-1]))
        print(repr(values[-100:100]))
        print("abcdef"[1:5:2])
        """
    )


def test_list_slice_assignment_and_deletion_match_python():
    assert_semantics(
        """\
        values = [0, 1, 2, 3, 4, 5]
        values[1:4] = [8, 9]
        print(repr(values))
        values[1:1] = [6, 7]
        print(repr(values))
        values[5:0:-2] = [10, 11, 12]
        print(repr(values))
        del values[4:0:-2]
        print(repr(values))
        values[::-1] = values
        print(repr(values))
        del values[-1]
        print(repr(values))
        mapping = {"one": 1, "two": 2}
        del mapping["one"]
        print(repr(mapping))
        """
    )


def test_invalid_slice_operations_raise_python_errors():
    assert_semantics(
        """\
        values = [0, 1, 2]
        try:
            print(repr(values[::0]))
        except Exception as error:
            print(str(error))
        try:
            values[::2] = [8]
        except Exception as error:
            print(str(error))
        try:
            del values[10]
        except Exception as error:
            print(str(error))
        mapping = {"present": 1}
        try:
            del mapping["missing"]
        except Exception as error:
            print(str(error))
        """
    )


def test_attribute_deletion_emits_a_valid_runtime_operation():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Item:
            def __init__(self):
                self.value = 1

        item = Item()
        del item.value
        print(hasattr(item, "value"))
        """
    )


def test_list_remove_uses_the_first_equal_value_and_reports_missing_values():
    assert_semantics(
        """\
        values = [1, 2, 1]
        values.remove(1)
        print(values[0], values[1])
        try:
            values.remove(9)
        except ValueError as error:
            print(str(error))
        """
    )


def test_sequence_index_and_list_remove_use_python_value_equality():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Match:
            def __init__(self, key: str):
                self.key = key

            def __eq__(self, other: Match) -> bool:
                return self.key == other.key

        values = [Match("first"), Match("second"), Match("first")]
        print(values.index(Match("first")))
        print(values.index(Match("first"), 1))
        print(values.index(Match("first"), -1, 20))
        values.remove(Match("first"))
        print(values[0].key, values[1].key)

        nested = [[1, 2], [3, 4]]
        print(nested.index([3, 4]))
        mappings = [{"first": 1}, {"second": 2}]
        print(mappings.index({"second": 2}))
        sets = [{1, 2}, {3, 4}]
        print(sets.index({4, 3}))

        numeric = [1, 2]
        print(numeric.index(True))

        coordinates = (1, 2, 1)
        print(coordinates.index(1, 1))
        matches = (Match("first"), Match("second"))
        print(matches.index(Match("second")))
        try:
            coordinates.index(3)
        except ValueError:
            print("tuple missing")

        try:
            values.index(Match("missing"))
        except ValueError:
            print("missing")
        """
    )


def test_sequence_index_clamps_negative_and_oversized_bounds():
    assert_semantics(
        """\
        values = [0, 1, 2, 1, 3]
        print(values.index(1, -4))
        print(values.index(1, -100, 100))
        print(values.index(1, 0, -1))

        coordinates = (0, 1, 2, 1, 3)
        print(coordinates.index(1, -4))
        print(coordinates.index(1, -100, 100))
        print(coordinates.index(1, 0, -1))

        try:
            values.index(1, 4, 2)
        except ValueError:
            print("missing")
        """
    )


def test_list_and_dict_clear_match_python():
    assert_semantics(
        """\
        values = [1, 2]
        list_result = values.clear()
        print(len(values), list_result is None)

        mapping = {"answer": 42}
        dict_result = mapping.clear()
        print(len(mapping), dict_result is None)
        """
    )


def test_dict_subscript_raises_key_error_while_get_returns_a_default():
    assert_semantics(
        """\
        mapping: dict[str, int | None] = {"present": 1, "empty": None}
        print(mapping["empty"] is None)
        print(mapping.get("missing", 2))
        try:
            print(mapping["missing"])
        except KeyError as error:
            print(str(error))
        """
    )


def test_non_string_mapping_keys_and_custom_subscripts_match_python():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Lookup:
            def __getitem__(self, key: str) -> int:
                return 42 if key == "answer" else 0

        mapping = {1: "one", 2: "two"}
        print(mapping[1])
        mapping[3] = "three"
        print(mapping[3], len(mapping))
        del mapping[2]
        print(2 in mapping, len(mapping))
        print(Lookup()["answer"])
        """
    )


def test_list_and_dict_clear_have_explicit_javascript_lowering():
    at(
        """\
        def main():
            values = [1, 2]
            list_result = values.clear()
            mapping = {"answer": 42}
            dict_result = mapping.clear()
        """,
        """
        def main() -> None:
            values: list[int] = [1, 2]
            list_result: None = values.[list__int]clear!()
            mapping: dict[str, int] = {'answer': 42}
            dict_result: None = mapping.[dict__str_int]clear!()
        """,
        """
        export function main() {
            var values = [1, 2];
            var list_result = (values.length = 0, null);
            var mapping = new Map([['answer', 42]]);
            var dict_result = (mapping.clear(), null);
        }
        """,
    )


def test_set_construction_operations_and_mutation_match_python():
    assert_semantics(
        """\
        values = set([1, 2, 2])
        empty = set[int]()
        print(values == {1, 2}, len(empty), bool(empty), isinstance(values, set))
        print(values != [1, 2], values != {1: "one", 2: "two"})
        print(set({"one": 1, "two": 2}) == {"one", "two"})
        print(set("aba") == {"a", "b"})

        copied = values.copy()
        values.add(3)
        values.discard(1)
        values.update([3, 4])
        print(values == {2, 3, 4}, copied == {1, 2})
        print(values.union({5}) == {2, 3, 4, 5})
        print(values.intersection({1, 2, 4}) == {2, 4})
        print(values.difference({2, 5}) == {3, 4})
        print(values.symmetric_difference({3, 5}) == {2, 4, 5})
        print(values | {5} == {2, 3, 4, 5})
        print(values & {1, 2, 4} == {2, 4})
        print(values - {2, 5} == {3, 4})
        print(values ^ {3, 5} == {2, 4, 5})
        print(values.isdisjoint({5, 6}))
        print(values.issubset({1, 2, 3, 4}))
        print(values.issuperset({2, 3}))
        print(values.issuperset([2, 3]))
        print({"one", "two"}.issuperset({"one": 1}))
        print({2, 3} < values, values > {2, 3})

        total = 0
        for value in values:
            total += value
        print(total)

        values.remove(2)
        removed = values.pop()
        print(removed not in values, len(values))
        values.clear()
        print(repr(values), bool(values))
        try:
            values.remove(9)
        except Exception:
            print("missing")
        try:
            values.pop()
        except Exception:
            print("empty")
        """
    )


def test_set_operations_accept_zero_or_multiple_iterables():
    assert_semantics(
        """\
        values = {1, 2, 3}
        print(values.union() == values)
        print(values.intersection() == values)
        print(values.difference() == values)
        print(values.union([3, 4], {5}) == {1, 2, 3, 4, 5})
        print(values.intersection([2, 3, 4], {3, 4}) == {3})
        print(values.difference([1], {3, 4}) == {2})
        result = values.update([4], {5, 6})
        print(result is None, values == {1, 2, 3, 4, 5, 6})
        """
    )


def test_mutating_set_operations_accept_python_call_shapes():
    assert_semantics(
        """\
        values = {1, 2, 3, 4}
        print(values.intersection_update())
        print(values == {1, 2, 3, 4})
        print(values.intersection_update([2, 3, 4], (3, 4, 5)))
        print(values == {3, 4})
        print(values.difference_update())
        print(values.difference_update([3], (9,)))
        print(values == {4})
        print(values.symmetric_difference_update([4, 5]))
        print(values == {5})
        same = {1, 2}
        same.difference_update(same)
        print(len(same))
        same = {1, 2}
        same.symmetric_difference_update(same)
        print(len(same))
        """
    )


def test_mutating_set_operations_have_explicit_runtime_lowering():
    at(
        """\
        def main(values: set[int]):
            intersection = values.intersection_update([1], {2})
            difference = values.difference_update([3], {4})
            symmetric = values.symmetric_difference_update([5])
        """,
        """
        def main(values: set__int) -> None:
            intersection: None = $intersection_update_set(values, [1], {2})
            difference: None = $difference_update_set(values, [3], {4})
            symmetric: None = $symmetric_difference_update_set(values, [5])
        """,
        """
        import { intersection_update_set as $intersection_update_set, difference_update_set as $difference_update_set, symmetric_difference_update_set as $symmetric_difference_update_set } from './pyjs.python.js';

        export function main(values) {
            var intersection = $intersection_update_set(values, [1], new Set([2]));
            var difference = $difference_update_set(values, [3], new Set([4]));
            var symmetric = $symmetric_difference_update_set(values, [5]);
        }
        """,
    )


def test_set_variadic_operations_have_explicit_runtime_lowering():
    at(
        """\
        def main(values: set[int]):
            copied = values.union()
            common = values.intersection([1, 2], {2, 3})
            remaining = values.difference([1], {2})
            result = values.update([4], {5})
        """,
        """
        def main(values: set__int) -> None:
            copied: set[int] = $union_set(values)
            common: set[int] = $intersection_set(values, [1, 2], {2, 3})
            remaining: set[int] = $difference_set(values, [1], {2})
            result: None = $update_set(values, [4], {5})
        """,
        """
        import { union_set as $union_set, intersection_set as $intersection_set, difference_set as $difference_set, update_set as $update_set } from './pyjs.python.js';

        export function main(values) {
            var copied = $union_set(values);
            var common = $intersection_set(values, [1, 2], new Set([2, 3]));
            var remaining = $difference_set(values, [1], new Set([2]));
            var result = $update_set(values, [4], new Set([5]));
        }
        """,
    )


def test_set_syntax_and_operators_have_explicit_javascript_lowering():
    at(
        """\
        def main():
            values = {1, 2}
            copied = set(values)
            empty = set[int]()
            values.add(3)
            values.discard(1)
            present = 2 in values
            combined = values | {4}
            common = values & {2}
            remaining = values - {2}
            changed = values ^ {3}
        """,
        """
        def main() -> None:
            values: set[int] = {1, 2}
            copied: set[int] = set__int(values)
            empty: set[int] = set__int()
            values.[set__int]add!(3)
            values.[set__int]discard!(1)
            present: bool = values.[set__int]__contains__!(2)
            combined: set[int] = values.[set__int]__or__!({4})
            common: set[int] = values.[set__int]__and__!({2})
            remaining: set[int] = values.[set__int]__sub__!({2})
            changed: set[int] = $symmetric_difference_set(values, {3})
        """,
        """
        import { union_set as $union_set, intersection_set as $intersection_set, difference_set as $difference_set, symmetric_difference_set as $symmetric_difference_set } from './pyjs.python.js';

        export function main() {
            var values = new Set([1, 2]);
            var copied = new Set(values);
            var empty = new Set();
            (values.add(3), null);
            (values.delete(1), null);
            var present = values.has(2);
            var combined = $union_set(values, new Set([4]));
            var common = $intersection_set(values, new Set([2]));
            var remaining = $difference_set(values, new Set([2]));
            var changed = $symmetric_difference_set(values, new Set([3]));
        }
        """,
    )


def test_empty_set_constructor_uses_assignment_annotation():
    at(
        """\
        def main():
            names: set[str] = set()
        """,
        """
        def main() -> None:
            names: set[str] = set__str()
        """,
        """
        export function main() {
            var names = new Set();
        }
        """,
    )


def test_container_operations_have_explicit_javascript_lowering():
    at(
        """\
        def main():
            parts = "one,two,three".split(",", 1)
            values = ["zero", "one", "two"]
            removed = values.pop(1)
            last = values[-1]
        """,
        """
        def main() -> None:
            parts: list[str] = $split_string('one,two,three', ',', 1)
            values: list[str] = ['zero', 'one', 'two']
            removed: str = $pop_list_item(values, 1)
            last: str = $get_list_item(values, -1)
        """,
        """
        import { split_string as $split_string, pop_list_item as $pop_list_item, get_list_item as $get_list_item } from './pyjs.python.js';

        export function main() {
            var parts = $split_string('one,two,three', {separator: ',', maxsplit: 1});
            var values = ['zero', 'one', 'two'];
            var removed = $pop_list_item(values, {index: 1});
            var last = $get_list_item(values, -1);
        }
        """,
    )


def test_sequence_item_operations_use_checked_runtime_helpers():
    at(
        """\
        def main(index: int):
            values = [1, 2]
            value = values[index]
            values[index] = 3
            pair = ("left", 2)
            first = pair[0]
            selected = pair[index]
            missing = pair[5]
            empty = ()
            absent = empty[0]
        """,
        """
        def main(index: int) -> None:
            values: list[int] = [1, 2]
            value: int = $get_list_item(values, index)
            $set_list_item(values, index, 3)
            pair: tuple[str, int] = ('left', 2)
            first: str = $get_tuple_item(pair, 0)
            selected: str | int = $get_tuple_item(pair, index)
            missing: str | int = $get_tuple_item(pair, 5)
            empty: tuple__ = ()
            absent: object = $get_tuple_item(empty, 0)
        """,
        """
        import { get_list_item as $get_list_item, set_list_item as $set_list_item, get_tuple_item as $get_tuple_item } from './pyjs.python.js';

        export function main(index) {
            var values = [1, 2];
            var value = $get_list_item(values, index);
            $set_list_item(values, index, 3);
            var pair = ['left', 2];
            var first = $get_tuple_item(pair, 0);
            var selected = $get_tuple_item(pair, index);
            var missing = $get_tuple_item(pair, 5);
            var empty = [];
            var absent = $get_tuple_item(empty, 0);
        }
        """,
    )
