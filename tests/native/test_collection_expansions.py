import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_literals_preserve_widths_mutation_and_operand_order(optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def change(items: list[int], value: int) -> list[int]:
            items[0] = value
            gc_collect()
            return [value]

        def fixed(values: tuple[int8, int64]) -> tuple[bool, int8, int64, list[str]]:
            return (True, *values, [])

        def collect(*values: int, last: int) -> str:
            return repr((values, last))

        def change_mapping(values: dict[str, int]) -> list[int]:
            values["saved"] = 99
            gc_collect()
            return [1]

        def named(**values: int) -> str:
            return repr(values)

        def main() -> str:
            gc_set_threshold(1)
            items = [1, 2]
            fields = fixed((int8(127), int64(9007199254740993)))
            first = (items[0], [*change(items, 3)])
            second = [*items, *change(items, 4), *items]
            third = (items[0], (*change(items, 5),))
            fourth = {"before": items[0], **{"after": len([*change(items, 6)])}}
            fifth = {items[0], *change(items, 7), items[0]}
            sixth = collect(0, *items, last=len([*change(items, 8)]))
            mapping = {"saved": 1}
            seventh = named(**mapping, last=len([*change_mapping(mapping)]))
            return repr((fields, fields[1] + int8(1), fields[2] + int64(1),
                         first, second, third, fourth, sorted(fifth), sixth, seventh))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansions_stay_in_lazy_branches_and_preserve_prior_reads(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def change(items: list[int], value: int) -> list[int]:
            items[0] = value
            gc_collect()
            return [value]

        def run(flag: bool) -> str:
            items = [1]
            first = items[0] + len([*change(items, 2)] if flag else [*change(items, 3)])
            second = flag and len([*change(items, 4)]) > 0
            third = flag or len([*change(items, 5)]) > 0
            fourth = 0 < len([*change(items, 6)]) < len([*change(items, 7)])
            fifth = 5 < len([*change(items, 8)]) < len([*change(items, 9)])
            return repr((first, second, third, fourth, fifth, items))

        def main() -> str:
            return run(False) + run(True)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansions_in_comprehensions_and_nested_lambdas_remain_deferred(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def mark(events: list[int], value: int) -> list[int]:
            gc_collect()
            events.append(value)
            return [value]

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            source = ([*mark(events, index)] for index in range(3))
            assert events == []
            first = next(source)
            assert events == [0]
            callback: Callable[[int], list[int]] = lambda value: [*mark(events, value)]
            assert events == [0]
            second = callback(4)
            callbacks: list[Callable[[], list[int]]] = [lambda: [*mark(events, index)] for index in range(2)]
            assert events == [0, 4]
            third = callbacks[0]()
            fourth = callbacks[1]()
            nested = [[*mark(events, index)] for index in range(3) if len([*mark(events, index)]) > 0]
            gc_collect()
            return repr((first, second, third, fourth, nested, list(source), events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


def test_dynamic_tuple_expansion_rejects_conflicting_storage_widths():
    with pytest.raises(CompilationError, match="Tuple items"):
        transpile_llvm('''
            from pyjs import int8, int64
            def main() -> int:
                fixed = (int8(1), int64(2))
                dynamic = [int8(3)]
                return len((*fixed, *dynamic))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind, count", [("set", 31), ("dict", 16), ("dict", 18)])
def test_ordinary_large_literal_hash_errors_skip_later_operands(optimize, kind, count):
    operands = [f"Key({index}, events)" for index in range(count)]
    if kind == "dict":
        operands = [f"{key}: {index}" for index, key in enumerate(operands)]
    literal = "{" + ", ".join(operands) + "}"
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect

        class Key:
            def __init__(self, value: int, events: list[str]):
                events.append("create " + str(value))
                self.value = value
                self.events = events
            def __hash__(self) -> int:
                self.events.append("hash " + str(self.value))
                gc_collect()
                if self.value == 5:
                    raise ValueError("hash failed")
                return self.value
            def __eq__(self, other: "Key") -> bool:
                return self.value == other.value

        def main() -> str:
            events: list[str] = []
            try:
                values = {literal}
                events.append(str(len(values)))
            except ValueError as error:
                events.append(str(error))
            gc_collect()
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
