import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
@pytest.mark.parametrize("binary", [False, True], ids=["unicode", "bytes"])
def test_text_slice_uses_one_checked_result_allocation(tmp_path, optimize, managed, binary):
    kind = "bytes" if binary else "str"
    original = b"\x00a\xffb\x80c" if binary else "aé\x00界😀é"
    sentinel = b"unchanged" if binary else "unchanged"
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def cut(value: {kind}, bounds: slice, mode: int) -> {kind}:
            if mode == 0:
                return value[:]
            if mode == 1:
                return value[::-1]
            if mode == 2:
                return value[1:16:3]
            if mode == 3:
                return value[::-9223372036854775808]
            if mode == 4:
                return value[5:2]
            return value[bounds]

        def main() -> int:
            original = {original!r} * 4
            bounds = slice(-2, 0, -2)
            sentinel = {sentinel!r}
            for mode in range(6):
                expected = cut(original, bounds, mode)
                result = sentinel
                arm(1000)
                result = cut(original, bounds, mode)
                stages = 1000 - remaining()
                arm(0)
                {'gc_collect()' if managed else 'pass'}
                if result != expected or stages != 1:
                    return 10 + mode
                result = sentinel
                caught = False
                arm(1)
                try:
                    result = cut(original, bounds, mode)
                except MemoryError:
                    caught = True
                arm(0)
                {'gc_collect()' if managed else 'pass'}
                if not caught or result is not sentinel:
                    return 20 + mode
                result = cut(original, bounds, mode)
                {'gc_collect()' if managed else 'pass'}
                if result != expected or original != {original!r} * 4:
                    return 30 + mode
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("binary", [False, True], ids=["unicode", "bytes"])
def test_text_slices_match_python_at_integer_boundaries(tmp_path, optimize, binary):
    values = [b"", b"\x00", b"\x00a\xffb\x80c"] if binary else ["", "😀", "aé\x00界😀é"]
    LLVM().assert_matches_python(f'''
        def main() -> str:
            bounds: list[int | None] = [None, -9223372036854775808, -9, -1, 0, 2, 9, 9223372036854775807]
            steps = [-9223372036854775808, -3, -1, 1, 2, 9223372036854775807]
            results: list[str] = []
            for value in {values!r}:
                for start in bounds:
                    for stop in bounds:
                        for step in steps:
                            results.append(repr(value[start:stop:step]))
                try:
                    results.append(repr(value[::0]))
                except ValueError as error:
                    results.append(str(error))
                try:
                    results.append(repr(value[slice(None, None, 0)]))
                except ValueError as error:
                    results.append(str(error))
            return "\\n".join(results)
    ''', directory=tmp_path, optimize=optimize)
