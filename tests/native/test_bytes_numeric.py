import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("annotation", ["str | bytes", "bytes | None", "str | None"])
@pytest.mark.parametrize("base", ["16", "base=16"])
def test_explicit_base_union_requires_located_narrowing(annotation, base):
    value = "None" if "None" in annotation else "b'ff'"
    with pytest.raises(LLVMUnsupported, match="explicit base requires narrowing its union input to str or bytes.*at line 2"):
        transpile_llvm(f"def parse(value: {annotation}) -> int:\n    return int(value, {base})\n"
                       f"def main() -> int:\n    return parse({value})\n")


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_numeric_literals_bases_and_invalid_spellings(optimize):
    # Preserved foundation cases plus byte-specific whitespace and error repr.
    result = LLVM().assert_matches_python(r'''
        def main() -> str:
            results: list[str] = []
            for value in (b"  -1_2 ", b"+1_2.5e1", b"0x_FF", b"0B_101", b"000",
                          b"",
                          b"1__2", b"0x1p2", b"1\x00", b"\x1c1", b"1\x1f",
                          b"\t\n\v\f\r +12 ", b"\xd9\xa1", b"\xc2\xa0" + b"1",
                          b"'\"\\", b"-0.0", b"+inf", b"NaN", b"1e309", b"1e-400"):
                for base in (0, 2, 10, 16, 36, 1, 37, -2):
                    try: results.append(str(int(value, base)))
                    except ValueError as error: results.append(str(error))
                try: results.append(str(float(value)))
                except ValueError as error: results.append(str(error))
            return repr((int(b"-7f", base=16), int(b"  -1_2 "),
                         int(b"-9223372036854775808"), int(b"9223372036854775807"), results))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_numeric_temporary_arguments_survive_collection(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        events: list[str] = []
        def value(text: str) -> bytes:
            events.append('value')
            return text.encode()
        def base(number: int) -> int:
            events.append('base')
            gc_collect()
            return number
        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            for text in ('-7f', '1__2', '١', '1.25'):
                for radix in (16, 1):
                    try: results.append(str(int(value(text), base(radix))))
                    except ValueError as error: results.append(str(error))
                try: results.append(str(float(value(text))))
                except ValueError as error: results.append(str(error))
            return repr((results, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_numeric_aliases_unions_and_lazy_map(optimize):
    result = LLVM().assert_matches_python('''
        from builtins import int as integer, float as floating
        from pyjs.native import gc_collect, gc_set_threshold
        def convert(value: str | bytes | int | None) -> str:
            try: return repr((integer(value), floating(value)))
            except TypeError: return 'none'
        def hexadecimal(value: str | bytes) -> int:
            if isinstance(value, bytes): return integer(value, 16)
            return integer(value, base=16)
        def main() -> str:
            gc_set_threshold(1)
            values = [b'12', b'-7', b'invalid', b'24']
            integers = map(integer, values)
            floats = map(floating, values)
            results: list[str] = []
            for _ in range(4):
                gc_collect()
                try: results.append(str(next(integers)))
                except ValueError as error: results.append(str(error))
                try: results.append(str(next(floats)))
                except ValueError as error: results.append(str(error))
            return repr((convert('13'), convert(b'14'), convert(15), convert(None),
                         hexadecimal('fe'), hexadecimal(b'ff'), results))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_bytes_numeric_preserves_all_byte_errors(tmp_path, optimize):
    source = '''
        def render(value: bytes, base: int) -> str:
            try: integer = str(int(value, base))
            except ValueError as error: integer = str(error)
            try: floating = str(float(value))
            except ValueError as error: floating = str(error)
            return repr((integer, floating))
    '''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        values = [value for byte in range(256)
                  for value in (bytes([byte]), b'1' + bytes([byte]), bytes([byte]) + b'1')]
        values += [b'!' * size for size in (197, 198, 199, 200, 201, 300)]
        values += [b'\xff' * 60, b'"\'' * 101]
        for value in values:
            for base in (0, 10, 36, 1):
                try:
                    integer = str(int(value, base))
                except ValueError as error:
                    integer = str(error)
                try:
                    floating = str(float(value))
                except ValueError as error:
                    floating = str(error)
                assert library.render(value, base) == repr((integer, floating)), (value, base)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_integer_overflow_keeps_native_i64_boundary(optimize):
    # CPython intentionally differs outside the documented signed-i64 range.
    result = LLVM().run_source('''
        def main() -> str:
            results: list[str] = []
            for value in (b'9223372036854775808', b'-9223372036854775809'):
                try: results.append(str(int(value)))
                except ValueError as error: results.append(str(error))
            return repr(results)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert not result.stderr
    assert result.stdout == repr(["integer value is outside native signed i64 range"] * 2)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("conversion", ["int", "float"])
def test_bytes_numeric_allocation_failures_unwind_and_recover(tmp_path, optimize, conversion):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm
        def parse(value: bytes) -> str:
            try: return str({conversion}(value))
            except ValueError as error: return str(error)
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            for text in ('12', '12.5', '1__2', '١'):
                value = text.encode()
                expected = parse(value)
                for stage in range(1, 24):
                    result = 'unassigned'
                    try:
                        arm(stage)
                        result = parse(value)
                        arm(0)
                        assert result == expected
                    except MemoryError:
                        arm(0)
                        caught += 1
                        assert result == 'unassigned'
                    finally:
                        arm(0)
                    gc_collect()
                    assert parse(value) == expected
            assert caught > 0
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
