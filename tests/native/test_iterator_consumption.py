import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", [
    "union", "update", "intersection", "intersection_update", "difference",
    "difference_update", "symmetric_difference", "symmetric_difference_update",
    "issubset", "issuperset", "isdisjoint",
])
def test_set_methods_preserve_cursor_tail(method, optimize):
    outcome = ('describe(sorted(result))' if method in {
        "union", "intersection", "difference", "symmetric_difference",
    } else 'str(result)')
    action = f"result = values.{method}(cursor)"
    if method.endswith("update"):
        action, outcome = f"values.{method}(cursor)", '"None"'
    LLVM().assert_matches_python(f'''
        def describe(values: list[int]) -> str:
            output = "["
            for value in values:
                output += str(value) + ","
            return output + "]"

        def main() -> str:
            output = ""
            initials: list[list[int]] = [[9], [1], [1, 2], []]
            for initial in initials:
                values = set(initial)
                cursor = iter([1, 1, 2, 3, 4])
                {action}
                output += {outcome} + describe(sorted(values)) + describe(list(cursor))
            return output
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", [
    "values.update([4], cursor)",
    "values.difference_update([4], cursor)",
    "values.intersection_update([1], cursor)",
    "values.symmetric_difference_update(cursor)",
])
def test_set_mutation_is_interleaved_or_atomic_as_required(operation, optimize):
    LLVM().assert_matches_python(f'''
        def main() -> str:
            values = {{1, 2, 3}}
            alias = values
            cursor = iter(values)
            outcome = "ok"
            try:
                {operation}
            except RuntimeError as error:
                outcome = str(error)
            return outcome + str(len(alias)) + str(4 in alias)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["update", "difference_update", "intersection_update"])
def test_set_partial_failure_across_operands(method, optimize):
    LLVM().assert_matches_python(f'''
        def main() -> str:
            values = {{1, 2, 3}}
            mapping = {{1: 1}}
            cursor = iter(mapping)
            mapping[4] = 4
            outcome = "ok"
            try:
                values.{method}([2, 4], cursor)
            except RuntimeError as error:
                outcome = str(error)
            for value in sorted(values):
                outcome += str(value)
            return outcome
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("rows, fallback", [
    ("zip(first, empty)", "(0, 0)"),
    ("enumerate(zip(first, empty))", "(-1, (0, 0))"),
    ("zip(enumerate(zip(first, empty)), [9, 8])", "((-1, (0, 0)), 0)"),
    ("zip(empty, zip(first, empty), strict=True)", "(0, (0, 0))"),
])
def test_exhausted_adapters_keep_advancing_shared_children(rows, fallback, optimize):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            first = iter([1, 2, 3, 4, 5, 6])
            empty: list[int] = []
            rows = {rows}
            next(rows, {fallback})
            gc_collect()
            next(rows, {fallback})
            return str(next(first, -1))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression, tail", [
    ("[2] in values", "next(values)[0]"),
    ("([1], 3) in zip(values, [3, 4, 5])", "next(values)[0]"),
])
def test_recursive_iterator_membership_includes_comparison_runtime(expression, tail, optimize):
    # No separate equality/sort call: it would hide a missing dependency.
    LLVM().assert_matches_python(f'''
        def main() -> str:
            values = iter([[1], [2], [3]])
            result = str({expression})
            return result + str({tail})
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_mutation_messages_propagate_through_nested_adapters(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            mapping = {1: 2}
            members = {1, 2}
            keys = iter(mapping)
            values = iter(mapping.values())
            items = iter(mapping.items())
            nested = enumerate(zip(iter(members), [1, 2]))
            mapping[3] = 4
            members.add(3)
            output = ""
            for attempt in range(2):
                try:
                    next(keys)
                except RuntimeError as error:
                    output += str(error)
                try:
                    next(values)
                except RuntimeError as error:
                    output += str(error)
                try:
                    next(items)
                except RuntimeError as error:
                    output += str(error)
                try:
                    next(nested)
                except RuntimeError as error:
                    output += str(error)
            return output
    ''', optimize=optimize)
