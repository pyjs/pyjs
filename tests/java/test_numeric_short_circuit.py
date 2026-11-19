import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import NUMERIC_SHORT_CIRCUIT_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_numeric_short_circuit_contract(tmp_path):
    assert_matches_python(NUMERIC_SHORT_CIRCUIT_CONTRACT.source, tmp_path)


def test_numeric_short_circuit_android_dex(tmp_path):
    assert_compiles_to_android_dex(NUMERIC_SHORT_CIRCUIT_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("kind, zero, value", [("int", "0", "-7"), ("float", "-0.0", "2.5")])
def test_operands_evaluate_once_and_skip_unused_effects(tmp_path, kind, zero, value):
    assert_text_matches_python(f'''
def operand(events: list[int], step: int, value: {kind}) -> {kind}:
    events.append(step)
    return value
def fail() -> {kind}:
    raise ValueError("must be skipped")
def main() -> str:
    events: list[int] = []
    a = operand(events, 1, {zero}) or operand(events, 2, {value}) or fail()
    b = operand(events, 3, {value}) and operand(events, 4, {zero}) and fail()
    assert a == {value} and b == {zero}
    assert len(events) == 4
    return str(events[0]) + str(events[1]) + str(events[2]) + str(events[3])
''', tmp_path)


def test_nan_is_truthy(tmp_path):
    assert_text_matches_python('''
from math import nan
def choose(value: float) -> float:
    return value or 4.0
def main() -> str:
    value = choose(nan)
    assert value != value
    return "preserved"
''', tmp_path)


def test_selected_numeric_bits_are_preserved(tmp_path):
    assert_text_matches_python('''
import struct
from pyjs import jvm
@jvm.native("java/lang/Double", name="doubleToRawLongBits")
def bits(value: float) -> int:
    return struct.unpack(">q", struct.pack(">d", value))[0]
def zero_and(value: float) -> float:
    return value and 4.0
def zero_or(value: float) -> float:
    return 0.0 or value
def fallback(value: int) -> int:
    return value or -9223372036854775808
def main() -> str:
    assert bits(zero_and(-0.0)) == -9223372036854775808
    assert bits(zero_or(-0.0)) == -9223372036854775808
    assert fallback(0) == -9223372036854775808
    assert fallback(9007199254740993) == 9007199254740993
    return "preserved"
''', tmp_path)


def test_mixed_numeric_result_domain_remains_explicit():
    with pytest.raises(JVMUnsupported, match="JVM union has incompatible runtime types"):
        transpile_jvm('''def choose(value: int) -> float:
    return value or 2.5
def main() -> float:
    return choose(0)
''')
