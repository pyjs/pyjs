import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
@pytest.mark.parametrize("binary", [False, True], ids=["unicode", "bytes"])
def test_trimming_uses_one_checked_result(tmp_path, optimize, managed, binary):
    kind = "bytes" if binary else "str"
    original = b"\xff\x00value\xc3\xa9\xff" if binary else "é😀\x00valueé"
    affix = b"\xff" if binary else "é"
    empty = b"" if binary else ""
    sentinel = b"unchanged" if binary else "unchanged"
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def trim(value: {kind}, chars: {kind} | None, mode: int) -> {kind}:
            if mode == 0:
                return value.removeprefix({affix!r})
            if mode == 1:
                return value.removesuffix({affix!r})
            if mode == 2:
                return value.removeprefix({empty!r})
            if mode == 3:
                return value.removesuffix({sentinel!r})
            if mode == 4:
                return value.strip(chars)
            if mode == 5:
                return value.lstrip(chars)
            if mode == 6:
                return value.rstrip(chars)
            return value

        def main() -> int:
            original = {original!r} * 2
            sentinel = {sentinel!r}
            characters: list[{kind} | None] = [None, {empty!r}, {affix!r}]
            for value in [{empty!r}, original]:
                for chars in characters:
                    for mode in range(7):
                        expected = trim(value, chars, mode)
                        arm(1000)
                        result = trim(value, chars, mode)
                        allocations = 1000 - remaining()
                        arm(0)
                        {'gc_collect()' if managed else 'pass'}
                        if result != expected or allocations != 1:
                            return 1
                        result = sentinel
                        caught = False
                        arm(1)
                        try:
                            result = trim(value, chars, mode)
                        except MemoryError:
                            caught = True
                        arm(0)
                        {'gc_collect()' if managed else 'pass'}
                        if not caught or result is not sentinel:
                            return 2
                        result = trim(value, chars, mode)
                        {'gc_collect()' if managed else 'pass'}
                        if result != expected or original != {original!r} * 2:
                            return 3
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_strip_and_affix_removal_preserve_python_semantics(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            characters: list[str | None] = [None, "", "é😀", "\\x00", "é"]
            for value in ["", "  é😀  ", "é😀middle😀é", "\\x1c\\u2003é\\u3000\\n", "\\x00a\\x00", "éé"]:
                for chars in characters:
                    results.append(value.strip(chars))
                    results.append(value.lstrip(chars))
                    results.append(value.rstrip(chars))
                    gc_collect()
                for affix in ["", "é", "é😀", "longer than the input", value]:
                    results.append(value.removeprefix(affix))
                    results.append(value.removesuffix(affix))
            byte_characters: list[bytes | None] = [
                None, b"", b" \\t\\n\\r\\v\\f", b"\\x00", b"\\xa9", b"\\xff\\xc3",
                bytes(range(256)),
            ]
            for value in [
                b"", b" \\t\\n\\r\\v\\f", b"\\xff\\x00abc\\xc3\\xa9\\xff",
                b" \\x1c\\x85\\xa0 ", b"\\xc3\\xa9", b"\\x00a\\x00", bytes(range(256)),
            ]:
                results.append(repr(value.strip()))
                results.append(repr(value.lstrip()))
                results.append(repr(value.rstrip()))
                for chars in byte_characters:
                    results.append(repr(value.strip(chars)))
                    results.append(repr(value.lstrip(chars)))
                    results.append(repr(value.rstrip(chars)))
                    gc_collect()
                for affix in [b"", b"\\xff", b"\\xc3", b"longer than the input", value]:
                    results.append(repr(value.removeprefix(affix)))
                    results.append(repr(value.removesuffix(affix)))
            return "|".join(results)
    ''', directory=tmp_path, optimize=optimize)
