import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import REPRESENTED_EXTREMA_DEFAULT_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_extrema_preserve_represented_defaults(tmp_path, optimize):
    contract = REPRESENTED_EXTREMA_DEFAULT_CONTRACT
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("default", ["int16(127)", "127"])
def test_union_extrema_defaults_cannot_change_numeric_domain(default):
    with pytest.raises(CompilationError, match="representation"):
        transpile_llvm(f'''from pyjs import int8, int16
def rank(value: int8 | None) -> int:
    return 0
def main() -> str:
    values: list[int8 | None] = []
    return repr(max(values, key=rank, default={default}))
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_extrema_preserve_selected_values_and_convert_defaults(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def rank(value: int | None) -> int:
            gc_collect()
            return 100 if value is None else value

        def text_rank(value: str | None) -> str:
            gc_collect()
            return "z" if value is None else value

        def main() -> str:
            gc_set_threshold(1)
            numbers: list[int | None] = [None, 3, 1]
            words: list[str | None] = [None, "b", "a"]
            empty_numbers: list[int | None] = []
            empty_words: list[str | None] = []
            return repr((min(numbers, key=rank), max(numbers, key=rank),
                         min(words, key=text_rank), max(words, key=text_rank),
                         min(empty_numbers, key=rank, default=7),
                         max(empty_numbers, key=rank, default=None),
                         min(empty_words, key=text_rank, default="fallback")))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_union_ordering_preserves_precision_and_stable_types(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def key(value: int) -> int | float | bool:
            gc_collect()
            if value == 0:
                return True
            if value == 1:
                return 1.0
            if value == 2:
                return 9007199254740993
            if value == 3:
                return 9007199254740992.0
            return -2

        def main() -> str:
            gc_set_threshold(1)
            empty: list[int | float | bool] = []
            values: list[int | float | bool] = [
                9007199254740993, 9007199254740992.0, True, 1.0, 1, False, -2.5,
            ]
            ascending = sorted(values)
            values.sort(reverse=True)
            indices = [2, 3, 0, 1, 4]
            return str((ascending, values, sorted(indices, key=key),
                        sorted(indices, key=key, reverse=True),
                        min(values), max(values), min(values[0], values[1]),
                        min(indices, key=key), max(indices, key=key),
                        min(empty, default=0), max(empty, default=False)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_union_tuple_keys_require_distinguishable_runtime_layouts():
    with pytest.raises(LLVMUnsupported, match="LLVM unions cannot distinguish different layouts of the same container class"):
        transpile_llvm('''
            def key(value: int) -> tuple[int] | tuple[int, int]:
                if value % 2 == 0:
                    return (0,)
                return (0, value)

            def main() -> str:
                return str(sorted([3, 2, 5, 0, 1, 4], key=key))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_union_keys_survive_collecting_comparisons(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Small:
            def __init__(self, value: int):
                self.value = value

            def __lt__(self, other: Small | Large) -> bool:
                gc_collect()
                return rank(self) < rank(other)

            def __gt__(self, other: Small | Large) -> bool:
                gc_collect()
                return rank(self) > rank(other)

        class Large:
            def __init__(self, value: int):
                self.value = value

            def __lt__(self, other: Small | Large) -> bool:
                gc_collect()
                return rank(self) < rank(other)

            def __gt__(self, other: Small | Large) -> bool:
                gc_collect()
                return rank(self) > rank(other)

        def rank(value: Small | Large) -> int:
            result = value.value
            if result == 7:
                raise RuntimeError("comparison failed")
            return result

        def key(value: int) -> Small | Large:
            gc_collect()
            if value % 2 == 0:
                return Small(value % 10)
            return Large(value % 10)

        class Empty:
            def __iter__(self) -> Iterator[Small | Large]:
                gc_collect()
                values: list[Small | Large] = []
                return iter(values)

        def consume(callback: Callable[[list[int]], int]) -> int:
            return callback([23, 11, 32, 21, 12, 43])

        def main() -> str:
            gc_set_threshold(1)
            errors: list[str] = []
            for operation in range(3):
                try:
                    if operation == 0:
                        sorted([21, 7, 3], key=key)
                    elif operation == 1:
                        min(map(key, [21, 7, 3]))
                    else:
                        max([21, 7, 3], key=key)
                    errors.append("missing exception")
                except RuntimeError as error:
                    errors.append(str(error))
                gc_collect()
            values = [23, 11, 32, 21, 12, 43]
            objects = [key(value) for value in values]
            empty: list[Small | Large] = []
            callback: Callable[[list[int]], int] = lambda items: min(items, key=key)
            return str((errors, sorted(values, key=key), sorted(values, key=key, reverse=True),
                        min(values, key=key), max(values, key=key), consume(callback),
                        [rank(item) for item in sorted(objects)],
                        rank(min(objects)), rank(max(objects)),
                        rank(min(map(key, values))), rank(max(map(key, values))),
                        rank(min(empty, default=Small(1))),
                        rank(max(empty, key=rank, default=Large(2))),
                        rank(min(Empty(), default=Small(9))),
                        rank(min(key(23), key(11), key(32))),
                        rank(max(key(23), key(11), key(32), key=rank))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr
