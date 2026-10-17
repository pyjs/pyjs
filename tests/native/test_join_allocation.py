import shutil
import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations, run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_join_keeps_tagged_literal_items_on_the_conversion_path(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Literal
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            rows: list[Literal['a', 'b']] = ['a', 'b']
            mapping: dict[Literal['a', 'b'], int] = {'a': 1, 'b': 2}
            pair: tuple[Literal['a', 'b'], ...] = ('a', 'b')
            gc_collect()
            return '|'.join(rows) + '/'.join(mapping) + '-'.join(pair)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
@pytest.mark.parametrize("binary", [False, True], ids=["unicode", "bytes"])
def test_join_borrows_collections_and_checks_output(tmp_path, optimize, managed, binary):
    kind = "bytes" if binary else "str"
    item = b"\xff\xc3\xa9\x00" if binary else "é😀\x00"
    separator = b"\x00\xff" if binary else "\x00→"
    empty = b"" if binary else ""
    sentinel = b"unchanged" if binary else "unchanged"
    source = transpile_llvm(f'''
        from pyjs import llvm
        from pyjs.native import gc_collect

        from tests.native.allocation_support import arm, remaining

        @llvm.inline("getelementptr %pyjs.string, ptr @test.oversized, i64 0")
        def oversized() -> {kind}:
            return {empty!r}

        def join(sep: {kind}, rows: list[{kind}], pair: tuple[{kind}, {kind}],
                 mapping: dict[{kind}, int], unique: set[{kind}], mode: int) -> {kind}:
            if mode == 0:
                return sep.join(rows)
            if mode == 1:
                return sep.join(pair)
            if mode == 2:
                return sep.join(mapping)
            return sep.join(unique)

        def main() -> int:
            original = {item!r} * 2
            sentinel = {sentinel!r}
            pair = (original, {empty!r})
            mapping = {{original: 1, sentinel: 2}}
            unique = {{original, sentinel}}
            for rows in [[], [original], [original, sentinel, {empty!r}]]:
                for sep in [{empty!r}, {separator!r}]:
                    for mode in range(4):
                        expected = join(sep, rows, pair, mapping, unique, mode)
                        arm(1000)
                        result = join(sep, rows, pair, mapping, unique, mode)
                        stages = 1000 - remaining()
                        arm(0)
                        {'gc_collect()' if managed else 'pass'}
                        if stages != 1 or result != expected:
                            print(mode)
                            print(stages)
                            return 1
                        result = sentinel
                        caught = False
                        arm(1)
                        try:
                            result = join(sep, rows, pair, mapping, unique, mode)
                        except MemoryError:
                            caught = True
                        arm(0)
                        {'gc_collect()' if managed else 'pass'}
                        if not caught or result is not sentinel:
                            return 2
                        result = join(sep, rows, pair, mapping, unique, mode)
                        {'gc_collect()' if managed else 'pass'}
                        if result != expected or original != {item!r} * 2:
                            return 3
            try:
                {empty!r}.join([oversized(), oversized()])
                return 4
            except MemoryError:
                pass
            return 0
    ''')
    source += (
        "\n@test.oversized = private constant %pyjs.string "
        "{ i64 9223372036854775807, ptr null }\n"
    )
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("binary", [False, True], ids=["unicode", "bytes"])
def test_join_checks_iterator_materialization(tmp_path, optimize, binary):
    kind = "bytes" if binary else "str"
    item = b"\xff\x00\xc3\xa9" if binary else "é😀\x00"
    separator = b"," if binary else ","
    sentinel = b"unchanged" if binary else "unchanged"
    source = transpile_llvm(f'''
        from collections.abc import Iterator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def items(value: {kind}) -> Iterator[{kind}]:
            for index in range(12):
                gc_collect()
                yield value

        def main() -> int:
            value = {item!r} * 2
            sentinel = {sentinel!r}
            expected = {separator!r}.join(items(value))
            iterator = items(value)
            arm(1000)
            result = {separator!r}.join(iterator)
            stages = 1000 - remaining()
            arm(0)
            gc_collect()
            if stages < 4 or result != expected:
                print(stages)
                print(result == expected)
                return 1
            for stage in range(1, stages + 1):
                result = sentinel
                iterator = items(value)
                caught = False
                arm(stage)
                try:
                    result = {separator!r}.join(iterator)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result is not sentinel:
                    return 2
                result = {separator!r}.join(items(value))
                gc_collect()
                if result != expected or value != {item!r} * 2:
                    return 3
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_join_preserves_python_collection_and_iterator_order(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            text = "é😀\\x00" * 2
            binary = b"\\xff\\xc3\\xa9\\x00" * 2
            text_mapping = {text: 1, "end": 2}
            byte_mapping = {binary: 1, b"end": 2}
            text_keys = text_mapping.keys()
            byte_keys = byte_mapping.keys()
            empty_text: tuple[str, ...] = ()
            empty_bytes: tuple[bytes, ...] = ()
            empty = ()
            gc_collect()
            result = [
                repr("|".join(())),
                repr(b"|".join(())),
                repr("|".join(empty)),
                repr(b"|".join(empty)),
                repr("|".join(empty_text)),
                repr(b"|".join(empty_bytes)),
                repr("|".join(frozenset([text]))),
                repr(b"|".join(frozenset([binary]))),
                repr("|".join(text_keys)),
                repr(b"|".join(byte_keys)),
                repr("|".join(text_mapping)),
                repr(b"|".join(byte_mapping)),
                repr("|".join((text, "", "end"))),
                repr(b"|".join((binary, b"", b"end"))),
                repr("|".join(iter((text, "", "end")))),
                repr(b"|".join(iter((binary, b"", b"end")))),
                repr("|".join(text)),
            ]
            gc_collect()
            return "\\n".join(result)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("mode", ["callback", "allocation"])
def test_failed_join_materializations_are_unrooted(tmp_path, mode):
    limiter = shutil.which("prlimit")
    if limiter is None:
        pytest.skip("requires Linux prlimit for bounded native execution")
    source = transpile_llvm(f'''
        from collections.abc import Iterator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def items() -> Iterator[str]:
            for index in range(8):
                yield "x" * 32768
                gc_collect()
            {'raise ValueError("iterator failed")' if mode == 'callback' else 'arm(1)'}

        def main() -> int:
            sentinel = "unchanged"
            for repeat in range(256):
                result = sentinel
                try:
                    result = ",".join(items())
                    return 1
                except {'ValueError' if mode == 'callback' else 'MemoryError'}:
                    pass
                arm(0)
                gc_collect()
                if result is not sentinel:
                    return 2
            return 0
    ''')
    executable = LLVM().compile(
        _fail_allocations(source, True), tmp_path, optimize=2,
    )
    # Abandoned materialization lists retain 64 MiB of generated items if their
    # temporary roots are not unwound on iterator or final-output failure.
    result = subprocess.run(
        [limiter, "--as=33554432", "--core=0", executable],
        capture_output=True, timeout=5,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
