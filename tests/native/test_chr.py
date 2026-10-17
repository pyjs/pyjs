import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import UNICODE_CHARACTER_CONTRACT


def test_shared_unicode_character_contract():
    result = LLVM().assert_matches_python(UNICODE_CHARACTER_CONTRACT.source)
    assert result.native.returncode == 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_chr_unicode_widths_and_owned_results(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int32, int64
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            values: list[str] = []
            for value in [0, 1, 127, 128, 2047, 2048, 0xd7ff, 0xe000,
                          0xfffe, 0xffff, 0x10000, 0x1f600, 0x10ffff]:
                text = chr(value)
                gc_collect()
                assert len(text) == 1 and ord(text) == value
                assert text.encode().decode() == text
                assert (text + 'x')[0] == text
                values.append(text)
            # Exercise interior values across every Unicode plane too.
            for value in range(0, 0x110000, 509):
                if value < 0xd800 or value > 0xdfff:
                    assert ord(chr(value)) == value
            values.extend([chr(False), chr(True), chr(int8(65)),
                           chr(int32(0x20ac)), chr(int64(0x1f600))])
            return repr(values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_chr_index_dispatch_order_and_failure_recovery(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        from pyjs.native import gc_collect, gc_set_threshold
        class Code(IntEnum):
            LETTER = 65
        class Base:
            pass
        class Index(Base):
            def __init__(self, value: int, events: list[str]):
                self.value, self.events = value, events
            def __index__(self) -> int:
                self.events.append('index')
                gc_collect()
                if self.value == 9:
                    raise RuntimeError('callback')
                return self.value
            def __int__(self) -> int:
                raise RuntimeError('must not use int')
        class IntOnly:
            def __int__(self) -> int:
                return 65
        def make(value: int, events: list[str]) -> Index:
            events.append('argument')
            return Index(value, events)
        def render(value: object) -> str:
            try:
                return chr(value)
            except TypeError:
                return 'TypeError'
            except ValueError as error:
                return str(error)
            except RuntimeError as error:
                return str(error)
        def nominal(value: Base) -> str:
            return chr(value)
        def tagged(value: Index | int | None) -> str:
            try:
                return chr(value)
            except TypeError:
                return 'None'
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            rows: list[str] = []
            for value in [65, -1, 0x110000, 9, 66,
                          -9223372036854775808, 9223372036854775807]:
                rows.append(render(make(value, events)))
            assert events == ['argument', 'index'] * 7
            values: list[object] = [None, 'a', 1.5, IntOnly(), Base(),
                                    True, Index(0x1f600, events)]
            rows.extend([render(value) for value in values])
            rows.append(chr(Code.LETTER))
            rows.append(nominal(Index(0x20ac, events)))
            rows.extend([tagged(None), tagged(67), tagged(Index(68, events))])
            repaired = Index(-1, events)
            rows.append(render(repaired))
            repaired.value = 69
            rows.append(render(repaired))
            return repr(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_chr_surrogate_boundary_does_not_publish_invalid_utf8(optimize):
    # Deliberate native ABI boundary, not CPython parity: CPython can construct
    # lone surrogates, while every native string consumer requires valid UTF-8.
    result = LLVM().run_source('''
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            for value in [0xd800, 0xdbff, 0xdc00, 0xdfff]:
                try:
                    chr(value)
                except ValueError as error:
                    assert str(error) == 'native chr() does not support lone surrogates'
                    caught += 1
                gc_collect()
            assert caught == 4
            assert ord(chr(0xd7ff)) == 0xd7ff
            assert ord(chr(0xe000)) == 0xe000
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0, result.stderr
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_chr_invalid_index_result_is_catchable_and_located(optimize):
    result = LLVM().assert_matches_python('''
        events: list[str] = []
        class Invalid:
            def __index__(self) -> str:
                events.append('index')
                return 'bad'
        def main() -> str:
            try:
                chr(Invalid())
            except TypeError:
                assert events == ['index']
                return chr(65)
            return 'missing error'
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
    # Checked protocol results now raise at runtime rather than rejecting the
    # function at compilation. The authored call site must still be preserved.
    failed = LLVM().run_source('''
        class Invalid:
            def __index__(self) -> str:
                return 'bad'
        def main() -> str:
            return chr(Invalid())
    ''', filename="chr_result.py", optimize=optimize, sanitizers=("address", "undefined"))
    assert failed.returncode != 0
    assert failed.stderr == (
        'Traceback (native PyJS):\n'
        '  File "chr_result.py", line 6, in main\n'
        'TypeError: __index__ returned a non-int value\n'
    )


def test_chr_argument_binding_and_stored_function_boundaries():
    with pytest.raises(CompilationError, match="positional-only"):
        transpile_llvm('def main() -> str: return chr(value=65)')
    with pytest.raises(LLVMUnsupported, match="one positional argument") as caught:
        transpile_llvm('def main() -> str: return chr(*[65])', filename="chr_pack.py")
    assert caught.value.__notes__ == [
        "Source location: chr_pack.py:1:27 (main; reported line above is function-relative)"
    ]
    with pytest.raises(CompilationError, match="cannot be used as a value"):
        transpile_llvm('''
            def main() -> str:
                callback = chr
                return callback(65)
        ''')
