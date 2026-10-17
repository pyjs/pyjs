import pytest

from pyjs.analysis.analyzer import analyzed_numeric_format
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import MODULAR_POWER_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_modular_power_contract(optimize):
    result = LLVM().assert_matches_python(MODULAR_POWER_CONTRACT.source, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, MODULAR_POWER_CONTRACT.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_enum_base_keeps_integer_power_slot_ahead_of_portable_exponent(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        from pyjs import int8, int64
        class Number(IntEnum):
            TWO = 2
            EIGHT = 8
        def main() -> str:
            enum_owned = pow(Number.TWO, int8(8), 257)
            wide_exponent = pow(Number.TWO, int64(8), 257)
            portable_owned = pow(int8(2), Number.EIGHT, 257)
            negative_modulus = pow(Number.TWO, int8(8), -257)
            inverse = pow(Number.TWO, int8(-1), 5)
            no_modulus = pow(Number.TWO, int8(8), None)
            binary = pow(Number.TWO, int8(8))
            return (str(enum_owned) + ':' + str(enum_owned + 1)
                    + ':' + str(wide_exponent + 1) + ':' + str(portable_owned + 1)
                    + ':' + str(negative_modulus) + ':' + str(inverse)
                    + ':' + str(no_modulus + 1) + ':' + str(binary + 1))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == '256:257:257:1:-1:3:257:257'
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_modular_power_errors_follow_operand_evaluation_and_preserve_inputs(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect
        def exponent(events: list[str], value: int) -> int:
            events.append('exponent')
            return value
        def modulus(events: list[str], value: int) -> int:
            gc_collect()
            events.append('modulus')
            return value
        def main() -> str:
            events: list[str] = []
            base = int8(2)
            for power in [-1, 0, 8]:
                for mod in [0, 1, -1, 4, 257]:
                    try:
                        value = pow(base, exponent(events, power), modulus(events, mod))
                        events.append(str(value))
                        events.append(str(value + 127))
                    except ValueError as error:
                        events.append(str(error))
            for mod in [0, 4]:
                try:
                    pow(2, exponent(events, -1), modulus(events, mod))
                except ValueError as error:
                    events.append(str(error))
            return repr(events) + str(base)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression, bits", [
    ("pow(int8(2), 8, 257)", 8), ("pow(2, int8(8), 257)", 8),
    ("pow(True, int8(8), 257)", None), ("pow(2, 8, int8(7))", None),
    ("pow(int64(2), 63, 127)", 64), ("pow(int8(2), 1000, None)", 8),
])
def test_modular_power_result_representation(environment, expression, bits):
    with analyze_source(f'''
        from pyjs import int8, int64
        def main():
            return {expression}
    ''', wrap=False, environment=environment) as analysis:
        returned = analysis.entry_point.ir.blocks[0].body[-1].value
        numeric = analyzed_numeric_format(returned)
        assert (numeric.bits if numeric else None) == bits
        representation = analysis.entry_point.return_representation
        assert (representation.numeric if representation else None) == numeric


@pytest.mark.parametrize("compiler,error", [(transpile_jvm, JVMUnsupported),
                                           (transpile_webassembly, WebAssemblyUnsupported)])
def test_other_native_targets_keep_modular_power_capability_boundary(compiler, error):
    with pytest.raises(error, match="pow"):
        compiler(MODULAR_POWER_CONTRACT.source)


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression,message", [
    ("pow(int8(2), int16(5), 7)", "different fixed-width numeric types"),
    ("pow(int8(2), 5, int16(7))", "different fixed-width numeric types"),
    ("pow(value, 5, 7)", r"fixed-width modular pow\(\) requires narrowed operands"),
    ("pow(int8(2), 5, modulus)", r"fixed-width modular pow\(\) requires narrowed operands"),
])
def test_modular_power_representation_boundaries(environment, expression, message):
    source = f'''
        from pyjs import int8, int16
        def power(value: int8 | bool, modulus: int | None):
            return {expression}
        def main():
            return power(int8(2), 7)
    '''
    with pytest.raises(CompilationError, match=message):
        with analyze_source(source, wrap=False, environment=environment):
            pass
