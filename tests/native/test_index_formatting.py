import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_base_builtins_preserve_widths_and_extremes(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64, uint32
        def main() -> str:
            values = [0, -1, 1, -9223372036854775808, 9223372036854775807]
            output = [bin(value) + "|" + oct(value) + "|" + hex(value) for value in values]
            output.append(bin(True) + hex(False))
            output.append(bin(int8(-128)) + oct(int64(9007199254740993)))
            output.append(hex(uint32(2**32 - 1)))
            return "\\n".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_index_formatting_uses_runtime_callbacks_and_checked_erased_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base: pass
        class Number(Base):
            def __init__(self, value: int): self.value = value
            def __index__(self) -> int:
                gc_collect()
                if self.value == 9: raise ValueError("index")
                self.value += 1
                return self.value
        def render(value: object) -> str:
            try:
                return bin(value) + "|" + oct(value) + "|" + hex(value)
            except TypeError:
                return "TypeError"
            except ValueError as error:
                return str(error)
        def concrete(value: Base) -> str:
            return hex(value)
        def optional(value: int | None) -> str:
            try: return oct(value)
            except TypeError: return "None"
        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [1, True, None, 1.5, "text", Base(), Number(3), Number(9)]
            return "\\n".join([render(value) for value in values]) + concrete(Number(5)) + optional(None) + optional(8)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_index_formatting_checks_return_values_after_callback_effects(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Invalid:
            def __init__(self, fail: bool):
                self.fail, self.calls = fail, 0
            def __index__(self) -> str:
                self.calls += 1
                gc_collect()
                if self.fail:
                    raise ValueError("callback")
                return "not an integer"
        def render(value: Invalid, operation: int) -> str:
            try:
                if operation == 0: return bin(value)
                if operation == 1: return oct(value)
                return hex(value)
            except TypeError:
                return "invalid"
            except ValueError:
                return "raised"
        def main() -> str:
            gc_set_threshold(1)
            result = ""
            for fail in [False, True]:
                value = Invalid(fail)
                for operation in range(3):
                    result += render(value, operation)
                assert value.calls == 3
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_index_callback_on_a_standalone_class(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Number:
            def __init__(self, value: int): self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        def render(value: object) -> str:
            return bin(value) + oct(value) + hex(value)
        def main() -> str:
            gc_set_threshold(1)
            return render(Number(16))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_base_builtins_unpack_narrowed_bool_int_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def render(value: int | str) -> str:
            if isinstance(value, int):
                return bin(value) + oct(value) + hex(value)
            return value
        def erased(value: object) -> str:
            if isinstance(value, int):
                return bin(value) + oct(value) + hex(value)
            return "other"
        def main() -> str:
            values: list[int | str] = [True, False, 7, -9, "text"]
            output = ""
            for value in values:
                output += render(value) + erased(value)
                if isinstance(value, int):
                    output += bin(value) + oct(value) + hex(value)
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
