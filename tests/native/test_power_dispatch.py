import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java.transpiler import transpile_jvm
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly.transpiler import transpile_webassembly
from tests.backend_semantics import BINARY_POWER_CONTRACT


@pytest.mark.parametrize("left", ["3", "int8(4)"])
@pytest.mark.parametrize("keywords", ["", ", **{}"])
def test_binary_power_and_operator_have_identical_llvm(left, keywords):
    source = f"from pyjs import int8\ndef main() -> int:\n    return int(pow({left}, 4{keywords}))\n"
    operator_source = source.replace(f"pow({left}, 4{keywords})", f"({left} ** 4)")
    assert transpile_llvm(source) == transpile_llvm(operator_source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_binary_power_contract(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        BINARY_POWER_CONTRACT.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0, BINARY_POWER_CONTRACT.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_binary_power_application_protocols_and_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from builtins import pow as builtin_pow
        from pyjs.native import gc_collect, gc_set_threshold

        class Value:
            def __init__(self, value: int, events: list[str]):
                self.value = value
                self.events = events
            def __pow__(self, other: "Value") -> "Value":
                self.events.append("pow")
                gc_collect()
                return Value(self.value ** other.value, self.events)

        class Reflected(Value):
            def __rpow__(self, other: Value) -> Value:
                self.events.append("reflected")
                gc_collect()
                return Value(other.value + self.value, self.events)

        class Shifted(Value):
            def __pow__(self, other: Value) -> Value:
                self.events.append("shifted")
                return Value(self.value - other.value, self.events)

        def left(events: list[str], fail: bool) -> Value:
            events.append("left")
            if fail:
                raise ValueError("left failed")
            return Value(3, events)

        def right(events: list[str], fail: bool) -> Reflected:
            events.append("right")
            if fail:
                raise ValueError("right failed")
            return Reflected(2, events)

        def invoke(value: Value) -> int:
            return pow(value, Value(2, value.events)).value

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            results: list[int] = []
            results.append(invoke(Value(3, events)))
            results.append(invoke(Shifted(8, events)))
            for fail_left in [False, True]:
                for fail_right in [False, True]:
                    try:
                        results.append(builtin_pow(left(events, fail_left), right(events, fail_right)).value)
                    except ValueError as error:
                        events.append(str(error))
            return repr((results, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_binary_power_numeric_representation_and_modular_fallback(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from builtins import pow as power
        from pyjs import int8, int64

        def square(value: int8) -> int8:
            return power(value, 2)

        def pow(left: int, right: int) -> int:
            return left + right

        def main() -> str:
            values: list[int8] = [power(int8(5), 3), square(int8(16))]
            large = power(int64(2), 62)
            flags = power(True, False)
            return repr((values, large, flags, type(flags) is int, pow(2, 3),
                         power(-2, 3), power(3, -1, 11),
                         power(2, 8, None), power(2, 8, 5)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize(("source", "message"), [
    ("from pyjs import int8, int16\ndef main() -> int: return pow(int8(2), int16(3))",
     "different fixed-width numeric types cannot be mixed implicitly"),
    ("from pyjs import float32\ndef main() -> float32: return pow(float32(2), 3)",
     r"Portable fixed-width floats do not support '\*\*'"),
    ("def main() -> int: return pow(2)", "missing required argument.*'exponent'"),
    ("def main() -> int: return pow(2, 3, 4, 5)", "too many positional arguments"),
    ("def main() -> int: return pow(base=2, exponent=3)", "parameter 'base' is positional-only"),
])
def test_binary_power_keeps_numeric_and_call_boundaries(source, message):
    with pytest.raises(CompilationError, match=message):
        transpile_llvm(source)


@pytest.mark.parametrize("transpile", [transpile_llvm, transpile_jvm, transpile_webassembly])
@pytest.mark.parametrize("expression", ["pow(2, *(3,))", "pow(*(2, 3, 5))"])
def test_power_unpacking_reports_the_call_site(transpile, expression):
    source = f"def main() -> int:\n    return {expression}\n"
    with pytest.raises(CompilationError, match=r"pow\(\) argument unpacking is not supported") as caught:
        transpile(source)
    assert caught.value.lineno == 2


@pytest.mark.parametrize("expression", ["pow(int8(2), int16(5), 7)", "pow(int8(2), 5, int16(7))"])
def test_modular_power_rejects_mixed_fixed_width_formats(expression):
    source = f"from pyjs import int8, int16\ndef main() -> int: return int({expression})"
    with pytest.raises(CompilationError, match="different fixed-width numeric types cannot be mixed implicitly"):
        transpile_llvm(source)
