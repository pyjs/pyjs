import pytest

from tests.java.test_exceptions import run_jvm


@pytest.mark.parametrize("item_type,value,expected", [
    ("bool", "True", "True"),
    ("int8", "int8(-128)", "-128"),
    ("uint8", "uint8(255)", "255"),
    ("int16", "int16(-32768)", "-32768"),
    ("uint16", "uint16(65535)", "65535"),
    ("i32", "i32(-2147483648)", "-2147483648"),
    ("uint32", "uint32(4294967295)", "4294967295"),
    ("int", "9007199254740993", "9007199254740993"),
    ("int64", "int64(-9223372036854775808)", "-9223372036854775808"),
    ("f32", "f32(1.25)", "True"),
    ("float", "1.25", "True"),
    ("str", '"日本語😀"', "日本語😀"),
])
def test_native_array_loop_preserves_item_storage(tmp_path, item_type, value, expected):
    observation = "value == 1.25" if item_type in {"f32", "float"} else "value"
    result = run_jvm(f'''
from pyjs import int8, uint8, int16, uint16, uint32, int64
from pyjs.java import JVMArray, i32, f32
def main() -> str:
    values = JVMArray[{item_type}](1)
    values[0] = {value}
    result = ""
    for value in values:
        result += str({observation})
    return result
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_array_loop_reads_later_mutations_and_evaluates_source_once(tmp_path):
    result = run_jvm('''
from pyjs.java import JVMArray, i32
class Source:
    def __init__(self):
        self.calls = 0
        self.values = JVMArray[i32](3)
        self.values[0] = i32(1)
        self.values[1] = i32(2)
        self.values[2] = i32(3)
    def get(self) -> JVMArray[i32]:
        self.calls += 1
        return self.values
def main() -> str:
    source = Source()
    result = ""
    for value in source.get():
        source.values[1] = i32(9)
        if value == 1:
            continue
        result += str(value)
    else:
        result += "done"
    for value in source.values:
        break
    else:
        result += "wrong"
    for value in JVMArray[i32](0):
        result += "wrong"
    else:
        result += "empty"
    return result + str(source.calls)
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "93doneempty1"


def test_nested_arrays_and_native_arguments_keep_item_representations(tmp_path):
    result = run_jvm('''
from pyjs import jvm
from pyjs.java import JVMArray, i32
@jvm.native("java/lang/Math", name="abs")
def absolute(value: i32) -> i32: ...
def main() -> str:
    rows = JVMArray[JVMArray[i32]](2)
    for index in range(2):
        rows[index] = JVMArray[i32](1)
        rows[index][0] = i32(-3 - index)
    result = ""
    for row in rows:
        for value in row:
            result += str(absolute(value))
    return result
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "34"


def test_native_reference_array_loop_and_rebound_source(tmp_path):
    result = run_jvm('''
from pyjs.java import JVMArray, StringBuilder
def main() -> str:
    values = JVMArray[StringBuilder](2)
    values[0] = StringBuilder().append("first")
    values[1] = StringBuilder().append("second")
    result = ""
    for value in values:
        values = JVMArray[StringBuilder](0)
        result += value.to_string()
    return result + str(len(values))
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "firstsecond0"
