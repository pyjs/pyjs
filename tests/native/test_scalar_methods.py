import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.native.runtime.text import SPACE_RANGES, WHITESPACE, _character_ranges
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly


def test_whitespace_ranges_are_coalesced_without_changing_membership():
    assert _character_ranges("") == ()
    assert _character_ranges("dbaab") == ((97, 98), (100, 100))
    assert len(SPACE_RANGES) == 10
    assert {code for start, stop in SPACE_RANGES for code in range(start, stop + 1)} == set(map(ord, WHITESPACE))


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_bit_methods_preserve_magnitude_and_ordinary_result(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int16, int32, int64, uint8, uint16, uint32
        from enum import IntEnum
        class Flag(IntEnum):
            HIGH = -128
        def counts(value: int) -> tuple[int, int]:
            return value.bit_count(), value.bit_length()
        def main() -> str:
            values = [0, 1, -1, 255, -255, 9223372036854775807,
                      -9223372036854775808, 9007199254740993]
            small_count: int = int8(-128).bit_count()
            small_length: int = int8(-128).bit_length()
            return repr(([counts(value) for value in values],
                         True.bit_count(), False.bit_length(),
                         small_count + 200, small_length + 200,
                         int16(-32768).bit_length(), int32(-2147483648).bit_count(),
                         int64(-9223372036854775808).bit_length(),
                         uint8(-1).bit_count(), uint16(-1).bit_length(),
                         uint32(-1).bit_count(), Flag.HIGH.bit_length()))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_methods_evaluate_receivers_once_and_keep_application_methods(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Counter:
            def bit_count(self) -> int: return 123
            def bit_length(self) -> int: return 456
            def isspace(self) -> bool: return True
        def integer(events: list[int]) -> int:
            events.append(1)
            return -255
        def text(events: list[int]) -> str:
            events.append(2)
            return chr(0x2003) + chr(0x3000)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            count = integer(events).bit_count()
            space = text(events).isspace()
            gc_collect()
            custom = Counter()
            alias = custom.bit_count
            return repr((count, space, events, alias(),
                         custom.bit_count(), custom.bit_length(), custom.isspace()))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["(3).bit_count", "(-3).bit_length", "' '.isspace"])
def test_extracted_builtin_methods_keep_existing_callable_boundary(expression):
    with pytest.raises(LLVMUnsupported, match="function values require an application function"):
        transpile_llvm(f'''
            def main() -> int:
                method = {expression}
                return int(method())
        ''')


@pytest.mark.parametrize("compile,error", [(transpile_jvm, JVMUnsupported),
                                         (transpile_webassembly, WebAssemblyUnsupported)],
                         ids=["jvm", "wasm"])
@pytest.mark.parametrize("expression,method", [("(3).bit_count()", "bit_count"),
                                               ("(-3).bit_length()", "bit_length"),
                                               ("' '.isspace()", "isspace")])
def test_shared_declarations_keep_other_backends_explicitly_unsupported(compile, error, expression, method):
    diagnostic = "value type str is not implemented" if compile is transpile_webassembly and method == "isspace" else method
    with pytest.raises(error, match=diagnostic):
        compile(f"def main() -> int:\n    return int({expression})\n")


@pytest.mark.parametrize("optimize", [0, 2])
def test_bit_methods_accept_narrowed_or_converted_numeric_unions(optimize):
    result = LLVM().assert_matches_python('''
        def counts(value: int | bool) -> tuple[int, int]:
            if isinstance(value, bool):
                return value.bit_count(), value.bit_length()
            else:
                return value.bit_count(), value.bit_length()
        def converted(value: int | bool) -> tuple[int, int]:
            return int(value).bit_count(), int(value).bit_length()
        def main() -> str:
            values: list[int | bool] = [-9223372036854775808, True, 0, False, -255]
            return repr([(counts(value), converted(value)) for value in values])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("method", ["bit_count", "bit_length"])
def test_unnarrowed_integer_methods_require_explicit_conversion(method):
    with pytest.raises(LLVMUnsupported, match="narrowed int may be bool; convert with int") as caught:
        transpile_llvm(f'''
            def count(value: int | bool) -> int:
                return value.{method}()
            def main() -> int:
                return count(True)
        ''')
    assert caught.value.node.lineno == 2
    assert any("(count;" in note for note in caught.value.__notes__)


@pytest.mark.parametrize("optimize", [0, 2])
def test_unicode_whitespace_and_neighbor_codepoints(optimize):
    # Derive expectations from CPython rather than importing the runtime's table.
    whitespace = [code for code in range(0x110000) if chr(code).isspace()]
    neighbors = sorted({code + delta for code in whitespace for delta in (-1, 0, 1)})
    source = f'''
        def main() -> str:
            codes = {neighbors!r}
            whitespace = {whitespace!r}
            joined = "".join([chr(code) for code in whitespace])
            values = [chr(code) for code in codes]
            values.extend(["", "a", chr(0), chr(0x1f600), joined,
                           joined + "a", "a" + joined, joined + chr(0)])
            return repr([value.isspace() for value in values])
    '''
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
