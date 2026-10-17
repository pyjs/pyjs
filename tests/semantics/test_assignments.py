import pytest

from tests.backend_semantics import (
    OPTIONAL_OBJECT_CONTRACT, UNION_NONE_GUARD_CONTRACT, UNPACK_FIELD_CONTRACT, UNPACK_TARGET_SOURCE,
)

from .helpers import assert_semantics


def test_nested_attribute_unpacking_checks_each_level_before_its_stores():
    source = UNPACK_TARGET_SOURCE.replace('def main() -> str:\n    return run()',
                                         'def main() -> None:\n    print(run())')
    assert_semantics(source + '\nmain()\n')


def test_shared_unpacking_field_contract():
    assert_semantics(UNPACK_FIELD_CONTRACT.print_source + '\nmain()\n')


@pytest.mark.parametrize("targets", ["box.left, box.right", "items[0], items[1]", "left, right"])
@pytest.mark.parametrize("starred_target", [False, True])
def test_starred_source_list_checks_actual_length_before_stores(targets, starred_target):
    if starred_target:
        targets = targets.replace(", ", ", *middle, ")
    assert_semantics(f'''
        from pyjs import js
        @js
        class Box:
            def __init__(self):
                self.left = -1
                self.right = -1
        @js
        def main() -> None:
            for count in range(5):
                source = list(range(count))
                box = Box()
                items = [-1, -1]
                left = -1
                right = -1
                middle = [-1]
                try:
                    {targets} = [*source]
                except ValueError as error:
                    print(str(error))
                print(box.left, box.right, str(items), left, right, str(middle))
        main()
    ''')


def test_unpacking_calls_property_setters_in_order_and_stops_on_failure():
    assert_semantics('''
        from pyjs import js
        @js
        class Box:
            def __init__(self):
                self.first = -1
                self._value = -1
                self.events: list[int] = []
            @property
            def value(self) -> int:
                return self._value
            @value.setter
            def value(self, value: int) -> None:
                self.events.append(value)
                if value == 2:
                    raise ValueError("setter")
                self._value = value
        @js
        def main() -> None:
            box = Box()
            for value in [2, 3]:
                try:
                    box.first, (box.value, box.first) = (1, (value, 9))
                except ValueError:
                    print("failed")
                print(box.first, box.value, str(box.events))
        main()
    ''')


def test_negation_uses_union_truth_and_length_fallback():
    assert_semantics('''
        from pyjs import js

        @js
        class Sized:
            def __len__(self) -> int:
                return 0

        @js
        def negate(value: int | str | None) -> bool:
            return not value

        @js
        def main():
            print(negate(None), negate(''), negate('x'), negate(0), negate(1), not Sized(), not None)

        main()
    ''')


def test_object_assignments_preserve_possible_none():
    assert_semantics(OPTIONAL_OBJECT_CONTRACT.print_source + "\nmain()\n")


def test_multiple_concrete_members_survive_none_guards():
    assert_semantics(UNION_NONE_GUARD_CONTRACT.print_source + "\nmain()\n")


def test_fixed_unpacking_evaluates_the_source_once():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def pair() -> tuple[int, str]:
            print("pair")
            return 1, "two"

        number, text = pair()
        print(number + 1)
        print(text + "!")
        """
    )


def test_list_target_and_source_unpack_by_position():
    assert_semantics(
        """\
        [first, second] = [3, 4]
        print(first)
        print(second)
        """
    )


def test_dynamic_list_unpacking_checks_too_few_and_too_many_values():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def values(short: bool) -> list[int]:
            return [1] if short else [1, 2, 3]

        for short in [True, False]:
            try:
                first, second = values(short)
            except Exception as error:
                print(str(error))
        """
    )


def test_starred_unpacking_collects_middle_values_and_checks_minimum_arity():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def values() -> list[int]:
            print("values")
            return [1, 2, 3, 4]

        @js
        def short() -> list[int]:
            return [1]

        first, *middle, last = values()
        print(first, len(middle), middle[0], middle[1], last)

        head, *empty = (1,)
        print(head, len(empty))

        *prefix, final = (1, 2, 3)
        print(len(prefix), prefix[0], prefix[1], final)

        number, (left, right), *tail = (1, [2, 3], 4, 5)
        print(number, left, right, len(tail), tail[0], tail[1])

        try:
            left, *rest, right = short()
        except ValueError as error:
            print(str(error))
        """
    )


def test_nested_and_attribute_unpacking_match_python():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Point:
            def __init__(self):
                self.x = 0
                self.y = 0

            def move(self, coordinates: tuple[int, int]):
                self.x, self.y = coordinates

        index, (name, score) = (1, ("Ada", 9))
        point = Point()
        point.move((3, 4))
        print(index, name, score)
        print(point.x, point.y)
        """
    )


def test_subscript_unpacking_and_swaps_match_python():
    assert_semantics(
        """\
        values = [[1], [2]]
        left = 0
        right = 1
        values[left], values[right] = values[right], values[left]
        print(values[0][0], values[1][0])

        first, values[right] = values[left], [3]
        print(first[0], values[right][0])

        mapping = {"left": 1, "right": 2}
        mapping["left"], mapping["right"] = (
            mapping["right"],
            mapping["left"],
        )
        print(mapping["left"], mapping["right"])

        values = [[1], [2]]
        try:
            values[0], values[3] = [3], [4]
        except IndexError:
            print(values[0][0], values[1][0])
        """
    )


def test_nested_loop_targets_match_python():
    assert_semantics(
        """\
        values = [(1, (2, 3)), (4, (5, 6))]
        for index, (left, right) in values:
            print(index, left, right)
        """
    )
