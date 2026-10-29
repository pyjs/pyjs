"""Python semantics at the JVM collection and math boundaries used by kernels."""
import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.classpath import read_jvm_class
from tests.backend_semantics import BENCHMARK_PRIMITIVE_CONTRACTS
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
    run_jvm,
)


@pytest.mark.parametrize("kind, items", [
    ("int", "[1, 2, 3, 4]"), ("float", "[1.5, 2.5, 3.5, 4.5]"),
    ("str", "['a', 'b', 'c', 'd']"), ("bool", "[True, False, True, False]"),
    ("str | None", "['a', None, 'c', 'd']"),
    ("list[int]", "[[1], [2], [3], [4]]"),
    ("int8", "[int8(1), int8(2), int8(3), int8(4)]"),
])
def test_list_pop_preserves_aliases_values_and_growth(tmp_path, kind, items):
    comparison = "is" if kind == "list[int]" else "=="
    assert_text_matches_python(f'''from pyjs import int8
def main() -> str:
    values: list[{kind}] = {items}
    alias = values
    expected = values[1]
    assert values.pop(1) {comparison} expected
    assert len(alias) == 3
    expected = values[2]
    assert values.pop() {comparison} expected
    expected = values[0]
    assert values.pop(-2) {comparison} expected
    assert len(values) == 1
    last = values.pop(False)
    assert len(alias) == 0
    values.append(last)
    assert alias[0] {comparison} last
    return "ok"
''', tmp_path)


def test_list_pop_errors_and_receiver_index_evaluation(tmp_path):
    assert_text_matches_python('''def receiver(values: list[int], events: list[str]) -> list[int]:
    events.append("receiver")
    return values
def index(values: list[int], events: list[str]) -> int:
    events.append("index")
    values.append(9)
    return -1
def main() -> str:
    values = [1, 2, 3]
    events: list[str] = []
    assert receiver(values, events).pop(index(values, events)) == 9
    assert ",".join(events) == "receiver,index"
    for offset in [-4, 3, 4294967296, -4294967296]:
        try:
            values.pop(offset)
        except IndexError as error:
            assert str(error) == "pop index out of range"
            assert len(values) == 3
        else:
            raise AssertionError("invalid index accepted")
    empty: list[int] = []
    try:
        empty.pop()
    except IndexError as error:
        assert str(error) == "pop from empty list"
    else:
        raise AssertionError("empty pop accepted")
    return "ok"
''', tmp_path)


def test_integer_dictionary_keys_and_missing_key_payload(tmp_path):
    assert_text_matches_python('''from typing import cast
def main() -> str:
    values: dict[int, int] = {1000: 1, -3: 2, 4294967296: 3}
    values[1000] = values.get(1000, 0) + 10
    values[1] = 7
    assert values[1] == 7 and 1 in values
    assert values.get(1001, 99) == 99
    assert values.setdefault(1000, 88) == 11
    assert values.setdefault(2, 8) == 8
    copied = values.copy()
    assert values.pop(1000) == 11
    assert values.pop(1000, 22) == 22
    assert copied[1000] == 11
    order = ""
    for key in values:
        order += str(key) + ","
    assert order == "-3,4294967296,1,2,"
    assert 1000 not in values
    try:
        values[1001]
    except KeyError as error:
        assert str(error) == "1001"
        assert cast(int, error.args[0]) == 1001
    else:
        raise AssertionError("missing key accepted")
    return "ok"
''', tmp_path)


@pytest.mark.parametrize("expression, expected", [
    ("math.sqrt(4.0)", 2.0), ("root(4)", 2.0), ("root(True)", 1.0),
    ("root(False)", 0.0), ("float(True)", 1.0), ("float(False)", 0.0),
])
def test_sqrt_imports_and_numeric_arguments(tmp_path, expression, expected):
    assert_text_matches_python(f'''import math
from math import sqrt as root
def main() -> str:
    assert {expression} == {expected}
    return "ok"
''', tmp_path)


def test_sqrt_domain_and_nonfinite_values(tmp_path):
    assert_text_matches_python('''import math
def main() -> str:
    assert math.sqrt(0.0) == 0.0
    assert math.sqrt(-0.0) == 0.0
    assert math.sqrt(1e309) == 1e309
    value = math.sqrt(1e309 - 1e309)
    assert value != value
    for invalid in [-1.0, -1e309]:
        try:
            math.sqrt(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("negative sqrt accepted")
    return "ok"
''', tmp_path)


@pytest.mark.parametrize("operation", ["values[True] = 7", "values.get(True, 0)", "True in values"])
def test_integer_dictionary_rejects_boolean_key_operands(operation):
    with pytest.raises(JVMUnsupported, match="integer dictionary keys do not support Boolean operands"):
        transpile_jvm(f'''def main() -> int:
    values: dict[int, int] = {{1: 2}}
    {operation}
    return 0
''')


def test_integer_keys_preserve_precision_null_values_and_evaluation_order(tmp_path):
    assert_text_matches_python('''def needle(events: list[str]) -> int:
    events.append("key")
    return 9007199254740993
def mapping(events: list[str], values: dict[int, str | None]) -> dict[int, str | None]:
    events.append("mapping")
    return values
def main() -> str:
    values: dict[int, str | None] = {
        9007199254740992: "first", 9007199254740993: None,
        -9223372036854775808: "minimum", 9223372036854775807: "maximum",
    }
    events: list[str] = []
    assert needle(events) in mapping(events, values)
    assert ",".join(events) == "key,mapping"
    events = []
    assert mapping(events, values).__contains__(needle(events))
    assert ",".join(events) == "mapping,key"
    assert values[9007199254740992] == "first"
    assert values.pop(9007199254740993, "fallback") is None
    assert values.pop(9007199254740993, "fallback") == "fallback"
    assert values[-9223372036854775808] == "minimum"
    assert values[9223372036854775807] == "maximum"
    try:
        for key in values:
            values[1000] = "changed"
    except RuntimeError:
        pass
    else:
        raise AssertionError("structural mutation accepted")
    return "ok"
''', tmp_path)


@pytest.mark.parametrize("kind", ["i32", "f32", "f64"])
def test_pop_retains_java_numeric_storage(tmp_path, kind):
    assert_matches_python(f'''from pyjs.java import {kind}
def main() -> int:
    values = [{kind}(1), {kind}(2), {kind}(3)]
    assert int(values.pop(1)) == 2
    assert int(values[0]) == 1 and int(values[1]) == 3
    assert int(values.pop()) == 3
    values.append({kind}(4))
    assert int(values.pop()) == 4
    return 0
''', tmp_path)


def test_sqrt_preserves_negative_zero_bits(tmp_path):
    result = run_jvm('''import math
from pyjs import jvm
@jvm.native("java/lang/Double", name="doubleToRawLongBits")
def bits(value: float) -> int: ...
def main() -> int:
    assert bits(math.sqrt(-0.0)) == -9223372036854775808
    assert bits(math.sqrt(0.0)) == 0
    return 0
''', tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("contract", BENCHMARK_PRIMITIVE_CONTRACTS.values(), ids=BENCHMARK_PRIMITIVE_CONTRACTS)
def test_benchmark_primitives_compile_to_android_dex(tmp_path, contract):
    assert_compiles_to_android_dex(contract.source, tmp_path)


def test_pop_helper_is_only_emitted_when_reachable():
    for operation, expected in [("", False), ("values.pop()", True)]:
        compilation = transpile_jvm(f'''def main() -> int:
    values = [1, 2]
    {operation}
    return len(values)
''')
        emitted = [method for data in compilation.classes.values()
                   for method in read_jvm_class(data).methods if method.name == "pop"]
        assert bool(emitted) is expected
