import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_application_ordering_can_handle_none(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        EVENTS: list[str] = []
        class Box:
            def __lt__(self, other: Box | None) -> bool:
                gc_collect()
                EVENTS.append("lt")
                return other is None
            def __gt__(self, other: Box | None) -> bool:
                gc_collect()
                EVENTS.append("gt")
                return other is not None
            def __le__(self, other: Box | None) -> bool:
                return self.__lt__(other)
            def __ge__(self, other: Box | None) -> bool:
                return self.__gt__(other)
        def main() -> str:
            cases: list[list[Box | None]] = [[], [None], [Box()], [None, Box()]]
            results: list[str] = []
            for left in cases:
                for right in cases:
                    results.append(str((left < right, left <= right, left > right, left >= right)))
            return str((results, EVENTS))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_union_sequences_preserve_exact_ordering_and_short_circuits(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def order(left: list[int | float | bool], right: list[int | float | bool]) -> str:
            gc_collect()
            return str((left < right, left <= right, left > right, left >= right,
                        tuple(left) < tuple(right), tuple(left) >= tuple(right)))

        def main() -> str:
            gc_set_threshold(1)
            cases: list[list[int | float | bool]] = [
                [], [False], [True], [1], [1.0], [1, 2.5], [1.0, 3],
                [9007199254740993], [9007199254740992.0],
                [-9223372036854775808], [-9223372036854775808.0],
                [float("inf")], [float("-inf")],
            ]
            result: list[str] = []
            for left in cases:
                for right in cases:
                    result.append(order(left, right))
            first: list[int | float | bool] = [float("nan")]
            second: list[int | float | bool] = [0]
            result.extend([order(first, second), order(second, first),
                           str((first < first, first <= first, first > first, first >= first))])
            return "|".join(result)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="Unboxed float storage does not retain NaN object identity")
def test_copied_sequences_preserve_nan_member_identity(tmp_path):
    LLVM().assert_matches_python('''
        def main() -> str:
            value = float("nan")
            return str((value,) <= (value,))
    ''', directory=tmp_path)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("item_type, cases", [
    ("int | str | None", '[[], [None], [1], ["a"], [1, None], [2, "a"], ["b", None]]'),
    ("list[int] | str | None", '[[], [None], [[1]], ["a"], [[1], None], [[2], "a"]]'),
    ("int | None", "[[], [None], [1], [2], [1, None]]"),
    ("str | None", '[[], [None], ["a"], ["b"], ["a", None]]'),
])
def test_union_ordering_raises_only_for_the_first_unequal_incompatible_pair(
    tmp_path, optimize, item_type, cases,
):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def order(left: list[ITEM], right: list[ITEM], mode: int) -> str:
            try:
                if mode == 0:
                    return str(left < right)
                if mode == 1:
                    return str(left <= right)
                if mode == 2:
                    return str(left > right)
                return str(left >= right)
            except TypeError as error:
                gc_collect()
                return str(error)

        def main() -> str:
            cases: list[list[ITEM]] = CASES
            output: list[str] = []
            for left in cases:
                for right in cases:
                    for mode in range(4):
                        output.append(order(left, right, mode))
            return "|".join(output)
    '''.replace("ITEM", item_type).replace("CASES", cases), directory=tmp_path, optimize=optimize)


def test_union_ordering_prepares_errors_without_explicit_string_operations(tmp_path):
    LLVM().assert_matches_python('''
        def main() -> int:
            left: list[int | str] = [1]
            right: list[int | str] = ["one"]
            try:
                return 1 if left < right else 2
            except TypeError:
                return 0
    ''', directory=tmp_path)


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_ordering_handles_fixed_fields_and_runtime_tuple_layouts(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def order(left: tuple[int | str, int | None], right: tuple[int | str | None, ...]) -> str:
            gc_collect()
            try:
                return str((left < right, left >= right, right <= left, right > left))
            except TypeError as error:
                return str(error)

        def main() -> str:
            fixed: list[tuple[int | str, int | None]] = [(1, None), (1, 2), ("a", None), ("b", 1)]
            dynamic: list[list[int | str | None]] = [[], [1], [1, None], [2, "later"], ["a", 3]]
            return "|".join([order(left, tuple(right)) for left in fixed for right in dynamic])
    ''', directory=tmp_path, optimize=optimize)
