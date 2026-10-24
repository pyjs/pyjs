import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pyjs import jvm
from pyjs.analysis.diagnostics import CompilationError
from pyjs.decorators import backend_metadata
from pyjs.java import (
    JVMTest,
    JVMUnsupported,
    current_time_millis,
    read_jvm_class,
    transpile_jvm,
)
from tests.backend_semantics import (
    ASSERT_NARROWING_CONTRACT,
    BACKEND_CONTRACTS,
    BINARY_POWER_CONTRACT,
    BOOLEAN_NUMERIC_CONTRACT,
    CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
    COLLECTION_NAME_CONTRACT,
    CUSTOM_ARITHMETIC_CONTRACT,
    FIELD_ASSIGNMENT_CONTRACT,
    GENERATOR_CLEANUP_CONTRACT,
    GENERIC_OPERATOR_CONTRACT,
    INHERITED_FACTORY_FIELD_CONTRACT,
    INHERITED_FIELD_ASSIGNMENT_CONTRACT,
    LITERAL_FIELD_ASSIGNMENT_CONTRACT,
    LITERAL_SEQUENCE_REFLECTION_CONTRACT,
    MAPPING_ASSIGNMENT_CONTRACT,
    MAPPING_LOOKUP_REPRESENTATION_CONTRACT,
    NESTED_CONDITIONAL_CONTRACT,
    NUMERIC_NAME_CONTRACT,
    PORTABLE_FAILURE_SOURCES,
    PROPERTY_FIELD_OVERRIDE_CONTRACT,
    RANGE_NUMERIC_LOOKUP_CONTRACT,
    RECURSIVE_EQUALITY_CONTRACT,
    RECURSIVE_OPTIONAL_CONTRACT,
    RECURSIVE_TREE_CONTRACT,
    REVERSED_PROTOCOL_CONTRACT,
    SEQUENCE_REFLECTION_CONTRACT,
    STRUCTURAL_OPERATOR_CONTRACT,
    TUPLE_INDEX_CONTRACT,
    UNION_KEY_REPRESENTATION_CONTRACT,
    UNION_REFLECTED_ARITHMETIC_CONTRACT,
    UNPACK_FIELD_CONTRACT,
)


def test_print_has_an_explicit_unsupported_output_diagnostic():
    with pytest.raises(JVMUnsupported, match=r"JVM print\(\) output is not implemented at line 2"):
        transpile_jvm("def main() -> int:\n    print('message')\n    return 0")


def test_boolean_arithmetic_has_an_explicit_jvm_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM scalar operation __add__"):
        transpile_jvm(BOOLEAN_NUMERIC_CONTRACT.source)


def test_range_lookup_keeps_the_jvm_first_class_range_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(RANGE_NUMERIC_LOOKUP_CONTRACT.source)


@pytest.mark.parametrize("invocation", ['dict(first="one")', 'dict(**{"first": "one"})'])
def test_dictionary_keywords_have_an_explicit_jvm_boundary(invocation):
    with pytest.raises(CompilationError, match=r"JVM dict\(\) keyword construction is not implemented") as caught:
        transpile_jvm(f"def main() -> int:\n    return len({invocation})\n", filename="dict_boundary.py")
    assert caught.value.filename == "dict_boundary.py"
    assert caught.value.lineno == 2


@pytest.mark.parametrize("source", ['values', 'values.items()', '[("a", "one")]'])
def test_dictionary_source_construction_has_an_explicit_jvm_boundary(source):
    with pytest.raises(CompilationError, match=r"JVM dict\(\) source construction is not implemented") as caught:
        transpile_jvm(f'''def main() -> int:
    values = {{"a": "one"}}
    return len(dict({source}))
''', filename="dict_source.py")
    assert caught.value.filename == "dict_source.py"
    assert caught.value.lineno == 3


def test_generator_cleanup_has_a_focused_unsupported_diagnostic():
    with pytest.raises(CompilationError, match="generator suspension is not implemented by this backend"):
        transpile_jvm(GENERATOR_CLEANUP_CONTRACT.source)


def test_reflected_mapping_union_has_an_explicit_jvm_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM dictionary operation __ror__"):
        transpile_jvm('''
def main() -> int:
    left = {"left": "value"}
    right = {"right": "value"}
    return len(left.__ror__(right))
''')


@pytest.mark.parametrize("target, message", [
    ("tuple[int8, ...]", "JVM variadic tuples require reference items"),
])
def test_explicit_sequence_constructor_has_a_jvm_capability_boundary(target, message):
    with pytest.raises(JVMUnsupported, match=message):
        transpile_jvm(f'''from pyjs import int8
def main() -> int:
    source = [int8(127)]
    copied = {target}(source)
    return int(copied[0] + 1)
''')


@pytest.mark.parametrize("name, argument, result", [
    ("hash", "1", "int"),
])
def test_native_value_builtins_keep_located_jvm_boundaries(name, argument, result):
    with pytest.raises(JVMUnsupported, match=f"JVM call target {name} has no emitted definition at line 2"):
        transpile_jvm(f"def main() -> {result}:\n    return {name}({argument})\n")


def test_application_round_keeps_a_located_jvm_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM expression .* at line 2"):
        transpile_jvm("class R:\n    def __round__(self) -> int: return 3\n"
                      "def main() -> int:\n    return round(R())\n")


def test_negation_uses_length_fallback(tmp_path):
    transpile_jvm('''
        class Sized:
            def __init__(self, size: int):
                self.size = size
            def __len__(self) -> int:
                return self.size
        def main() -> int:
            return 0 if not Sized(0) and not (not Sized(4)) and not None else 1
    ''').write(tmp_path)
    result = subprocess.run([java(), "-cp", str(tmp_path), "PyjsProgram"], capture_output=True)
    assert result.returncode == 0, result.stderr


CONTROL_FLOW_SOURCE = """
def choose(flag: bool, left: int, right: int) -> int:
    selected = left if flag else right
    return selected + 1


def main() -> int:
    value = 0
    while value < 4:
        value = value + 1
    return choose(value == 4, value, 0)
"""
OBJECT_SOURCE = """
class Marker:
    pass


class Point:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y

    def total(self) -> int:
        return self.x + self.y


def move(point: Point, amount: int) -> int:
    point.x = point.x + amount
    return point.total()


def main() -> int:
    count = 0
    while count < 10000:
        Marker()
        count = count + 1
    point = Point(y=3, x=2)
    return move(point, 4)
"""
COLLECTION_SOURCE = """
def main() -> int:
    values = [1, 2]
    total = 0
    for value in values:
        total = total + value
        if value == 2:
            values.append(3)
    pairs = [(1, 2), (3, 4)]
    for left, right in pairs:
        total = total + left + right
    for index in range(3, -1, -1):
        total = total + index
    return total + values[-1] + len(values)
"""
STRING_SOURCE = """
def build(prefix: str, index: int) -> str:
    return f"{prefix}-{index}" + " ✓"


def main() -> int:
    value = build("row", 42)
    if value != "row-42 ✓":
        return 1
    if not value:
        return 2
    if str(True) != "True":
        return 4
    utf8 = "café 😀 \\x00" + "finished"
    if utf8 != "café 😀 \\x00finished":
        return 8
    if str(-7) == "-7":
        return 17
    return 3
"""
STRING_OUTPUT_SOURCE = """
def render(prefix: str, count: int) -> str:
    return f"{prefix}: {count} ✓"


def main() -> str:
    return render("café 😀 \\x00", 42)
"""
ARRAY_SOURCE = """
from pyjs import jvm
from pyjs.java import JVMArray, i32


@jvm.native("java/util/Arrays", name="binarySearch")
def binary_search(values: JVMArray[i32], key: i32) -> i32:
    pass


def last(values: JVMArray[i32]) -> i32:
    return values[len(values) - 1]


def main() -> int:
    values = JVMArray[i32](3)
    values[0] = i32(2)
    values[1] = i32(4)
    values[2] = i32(8)
    return last(values) + len(values) + binary_search(values, i32(4))
"""
OPTIONAL_REFERENCE_SOURCE = """
from typing import Annotated

from pyjs import jvm
from pyjs.java.primitives import Reference

ObjectString = Annotated[str, Reference("java/lang/Object")]


@jvm.native("java/lang/System", name="getProperty")
def get_property(name: str) -> str | None:
    pass


@jvm.native("java/util/Objects", name="isNull")
def is_null(value: ObjectString | None) -> bool:
    pass


def empty() -> str | None:
    return None


def main() -> int:
    missing = get_property("pyjs.property.that.does.not.exist")
    if missing is None and empty() is None and is_null(None):
        return 0
    return 1
"""
INHERITANCE_SOURCE = """
class Animal:
    def __init__(self, value: int):
        self.value = value

    def sound(self) -> int:
        return self.value


class Cat(Animal):
    pass


class Dog(Animal):
    def __init__(self, value: int, bonus: int):
        super().__init__(value)
        self.bonus = bonus

    def sound(self) -> int:
        return self.value + self.bonus

    def reward(self) -> int:
        return self.bonus

    def parent_sound(self) -> int:
        return super().sound()


class Puppy(Dog):
    def reward(self) -> int:
        return self.bonus + 1


def speak(animal: Animal) -> int:
    return animal.sound()


def reward(dog: Dog) -> int:
    return dog.reward()


def main() -> int:
    dog = Dog(3, 4)
    cat = Cat(6)
    puppy = Puppy(2, 5)
    return speak(dog) + speak(cat) + reward(puppy) + dog.parent_sound()
"""
INTEGER_SEMANTICS_SOURCE = """
def main() -> int:
    if -7 // 3 != -3:
        return 1
    if -7 % 3 != 2:
        return 2
    if 7 // -3 != -3:
        return 3
    if 7 % -3 != -2:
        return 4
    if -7 // -3 != 2:
        return 5
    if -7 % -3 != -1:
        return 6
    if 7 // 3 != 2:
        return 7
    if 7 % 3 != 1:
        return 8
    return 29
"""
NATIVE_DECLARATION_SOURCE = """
from pyjs.java import current_time_millis


def main() -> int:
    if current_time_millis() > 0:
        return 31
    return 1
"""
NATIVE_OBJECT_SOURCE = """
from pyjs.java import StringBuilder


def main() -> str:
    builder = StringBuilder()
    builder.append("native ")
    builder.append("JVM ✓")
    return builder.to_string()
"""
NATIVE_CONSTRUCTOR_SOURCE = """
from pyjs import jvm


@jvm.native("java/lang/StringBuilder")
class Builder:
    def __init__(self, value: str) -> None:
        self.value = value

    @jvm.native(
        "java/lang/StringBuilder",
        name="toString",
        invocation="virtual",
    )
    def to_string(self) -> str:
        return self.value


def main() -> str:
    return Builder(value="argument ✓").to_string()
"""
NATIVE_PRIMITIVE_SOURCE = """
from pyjs import jvm
from pyjs.java import f32, f64, i32


@jvm.native("java/lang/Integer", name="rotateLeft")
def rotate_left(value: i32, distance: i32) -> i32:
    return value


@jvm.native("java/lang/Integer", name="rotateLeft")
def rotate_left_default(value: i32, distance: i32 = 3) -> i32:
    return value


@jvm.native("java/lang/Math", name="round")
def round_float(value: f32) -> i32:
    return int(value)


@jvm.native("java/lang/Math", name="sqrt")
def square_root(value: f64) -> f64:
    return value**0.5


@jvm.native("java/lang/Double", name="doubleToRawLongBits")
def double_bits(value: f64) -> int:
    return 0


@jvm.native("java/lang/Float", name="intBitsToFloat")
def bits_float(value: i32) -> f32:
    return 0.0


@jvm.native("java/lang/StringBuilder")
class NumberBuilder:
    def __init__(self, capacity: i32) -> None:
        self.value = ""

    @jvm.native(
        "java/lang/StringBuilder",
        name="append",
        invocation="virtual",
    )
    def append_int(self, value: i32) -> NumberBuilder:
        self.value += str(value)
        return self

    @jvm.native(
        "java/lang/StringBuilder",
        name="toString",
        invocation="virtual",
    )
    def to_string(self) -> str:
        return self.value


def preserve_float(value: float) -> float:
    copied = value
    return -(-copied)


def main() -> int:
    if rotate_left(1, 3) != 8:
        return 1
    if rotate_left_default(1) != 8:
        return 7
    if rotate_left(0x100000001, 1) != 2:
        return 4
    if rotate_left(0x40000000, 1) != -0x80000000:
        return 5
    if round_float(3.5) != 4:
        return 2
    if round_float(16777217.0) != 16777216:
        return 6
    if preserve_float(float(square_root(81.0))) != 9.0:
        return 3
    if double_bits(-0.0) != -0x7FFFFFFFFFFFFFFF - 1:
        return 7
    if bits_float(0x41100000) != 9.0:
        return 8
    if NumberBuilder(8).append_int(42).to_string() != "42":
        return 9
    return 37
"""
TRACEBACK_SOURCE = """
def divide(value: int) -> int:
    return value // 0


def calculate(value: int) -> int:
    return divide(value)


def main() -> int:
    return calculate(7)
"""
NATIVE_FIELD_SOURCE = """
from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.java import i32


@jvm.native("java/lang/Integer")
class Integer:
    MAX_VALUE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0


@jvm.native("java/awt/Point")
class Point:
    horizontal: Annotated[i32, jvm.field(name="x")]
    y: Annotated[i32, jvm.field()]

    def __init__(self, x: i32, y: i32) -> None:
        self.horizontal = x
        self.y = y


def main() -> int:
    point = Point(3, 4)
    point.horizontal = point.horizontal + 5
    if Integer.MAX_VALUE != 2147483647:
        return 1
    return point.horizontal + point.y
"""
NATIVE_INTERFACE_SOURCE = """
from pyjs import jvm


@jvm.native("java/lang/Runnable", interface=True)
class Runnable:
    def run(self) -> None:
        pass


@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self, target: Runnable) -> None:
        self.target = target

    def run(self) -> None:
        self.target.run()


class Callback(Runnable):
    def __init__(self) -> None:
        self.value = 0

    def run(self) -> None:
        self.value = self.value + 20


def execute(callback: Runnable) -> None:
    callback.run()


def main() -> int:
    callback = Callback()
    execute(callback)
    Thread(callback).run()
    return callback.value
"""
NATIVE_SUPERCLASS_SOURCE = """
from pyjs import jvm


@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self) -> None:
        pass

    def run(self) -> None:
        pass


class Worker(Thread):
    def __init__(self) -> None:
        self.value = 0

    def run(self) -> None:
        super().run()
        self.value = 43


def execute(thread: Thread) -> None:
    thread.run()


def main() -> int:
    worker = Worker()
    execute(worker)
    return worker.value
"""
FLOAT_ARITHMETIC_SOURCE = """
from pyjs.java import double_to_string, parse_double


def calculate(left: float, right: float) -> float:
    return (left + right) * (left - right) / right


def main() -> int:
    result = calculate(parse_double("7.5"), 2.5)
    if result != 20.0:
        return 1
    if -(-result) != result:
        return 2
    if not result:
        return 3
    if double_to_string(result) != "20.0":
        return 4
    return 44
"""
EXPECTED_BYTECODE = Path(__file__).with_name("control_flow.javap")


def java():
    executable = shutil.which("java")
    if executable is None:
        pytest.skip("a Java runtime is required for JVM backend tests")
    return executable


def write_class(tmp_path, source, class_name="PyjsProgram"):
    return transpile_jvm(source, class_name=class_name).write(tmp_path)


def test_jvm_transpiler_emits_a_directly_executable_class(tmp_path):
    output = write_class(tmp_path, CONTROL_FLOW_SOURCE)

    generated = output.read_bytes()
    assert generated[:8] == bytes.fromhex("cafebabe00000031")

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 5


def test_jvm_uses_python_bodies_not_javascript_clients(tmp_path):
    from tests.backend_semantics import CLIENT_IMPLEMENTATIONS_SOURCE
    write_class(tmp_path, CLIENT_IMPLEMENTATIONS_SOURCE)
    result = subprocess.run([java(), "-cp", str(tmp_path), "PyjsProgram"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 107, result.stderr
    assert not result.stdout and not result.stderr


def test_jvm_transpiler_executes_integer_abs(tmp_path):
    write_class(
        tmp_path,
        "def main() -> int:\n    return abs(-41) + abs(True)\n",
    )

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 42


def test_jvm_arrays_cross_native_boundaries_and_support_indexing(tmp_path):
    write_class(tmp_path, ARRAY_SOURCE)

    result = subprocess.run(
        [java(), "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 12


def test_jvm_optional_references_cross_native_boundaries(tmp_path):
    write_class(tmp_path, OPTIONAL_REFERENCE_SOURCE)

    result = subprocess.run(
        [java(), "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 0


def test_jvm_transpiler_executes_float_abs(tmp_path):
    write_class(
        tmp_path,
        """
def magnitude(value: float) -> float:
    return abs(value)


def main() -> int:
    if magnitude(-42.5) == 42.5:
        return 0
    return 1
""",
    )

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 0


def test_jvm_transpiler_matches_complete_bytecode_golden(tmp_path):
    output = write_class(tmp_path, CONTROL_FLOW_SOURCE)

    result = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == EXPECTED_BYTECODE.read_text()


def test_jvm_transpiler_uses_typed_gc_managed_application_objects(tmp_path):
    compilation = transpile_jvm(OBJECT_SOURCE)
    compilation.write(tmp_path)

    assert set(compilation.classes) == {
        "PyjsProgram",
        "PyjsProgram$Marker",
        "PyjsProgram$Point",
    }
    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 9

    point = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(tmp_path / "PyjsProgram$Point.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        point.stdout
        == """\
Compiled from "_pyjs_java_.py"
public final class PyjsProgram$Point {
  public long x;
  public long y;
  public PyjsProgram$Point();
  public void pyjs_init(long, long);
  public long total();
}
"""
    )


def test_jvm_transpiler_uses_specialized_lists_and_live_iteration(tmp_path):
    compilation = transpile_jvm(COLLECTION_SOURCE)
    compilation.write(tmp_path)

    assert {
        "PyjsProgram$list$J",
        "PyjsProgram$tuple$J$J",
        "PyjsProgram$list$LPyjsProgram$tuple$J$J_",
    } < compilation.classes.keys()
    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 28

    list_class = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(tmp_path / "PyjsProgram$list$J.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        list_class.stdout
        == """\
public final class PyjsProgram$list$J {
  public long[] data;
  public int length;
  public PyjsProgram$list$J();
  public void append(long);
  public long get(long);
  public void set(long, long);
  public void insert(long, long);
}
"""
    )


@pytest.mark.parametrize(
    "contract",
    BACKEND_CONTRACTS.values(),
    ids=BACKEND_CONTRACTS,
)
def test_jvm_runs_shared_numeric_contracts(tmp_path, contract):
    compilation = transpile_jvm(contract.source)
    compilation.write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 0, contract.failure(result.returncode)


@pytest.mark.parametrize("contract", [CUSTOM_ARITHMETIC_CONTRACT, SEQUENCE_REFLECTION_CONTRACT,
                                     STRUCTURAL_OPERATOR_CONTRACT])
def test_jvm_custom_arithmetic_protocols(tmp_path, contract):
    test_jvm_runs_shared_numeric_contracts(tmp_path, contract)


def test_jvm_binary_power_contract(tmp_path):
    test_jvm_runs_shared_numeric_contracts(tmp_path, BINARY_POWER_CONTRACT)


def test_generic_operator_contract_retains_jvm_type_boundary():
    # Generic inherited construction is not a supported JVM runtime shape yet.
    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(GENERIC_OPERATOR_CONTRACT.source)


def test_assert_narrowing_retains_the_jvm_union_storage_boundary():
    with pytest.raises(JVMUnsupported, match="JVM union has incompatible runtime types"):
        transpile_jvm(ASSERT_NARROWING_CONTRACT.source)


def test_jvm_reversed_protocol_contract(tmp_path):
    test_jvm_runs_shared_numeric_contracts(tmp_path, REVERSED_PROTOCOL_CONTRACT)


def test_jvm_literal_sequence_reflection_contract(tmp_path):
    test_jvm_runs_shared_numeric_contracts(tmp_path, LITERAL_SEQUENCE_REFLECTION_CONTRACT)


def test_mapping_lookup_contract_has_explicit_setdefault_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM dictionary operation setdefault"):
        transpile_jvm(MAPPING_LOOKUP_REPRESENTATION_CONTRACT.source)


def test_union_key_representation_contract_has_explicit_jvm_boundary():
    with pytest.raises(JVMUnsupported, match="JVM dictionaries do not support nullable numeric keys"):
        transpile_jvm(UNION_KEY_REPRESENTATION_CONTRACT.source)


def test_scalar_set_relations_have_an_explicit_jvm_boundary():
    from tests.backend_semantics import SCALAR_SET_RELATIONS_CONTRACT

    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(SCALAR_SET_RELATIONS_CONTRACT.source)


def test_set_constructor_representation_has_an_explicit_jvm_boundary():
    from tests.backend_semantics import SET_CONSTRUCTOR_REPRESENTATION_CONTRACT

    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(SET_CONSTRUCTOR_REPRESENTATION_CONTRACT.source)


@pytest.mark.parametrize("contract", [RECURSIVE_TREE_CONTRACT, RECURSIVE_OPTIONAL_CONTRACT, RECURSIVE_EQUALITY_CONTRACT])
def test_recursive_tree_contract_has_explicit_layout_boundary(contract):
    with pytest.raises(JVMUnsupported, match="recursive value layouts are not implemented"):
        transpile_jvm(contract.source)


def test_jvm_application_collection_names(tmp_path):
    test_jvm_runs_shared_numeric_contracts(tmp_path, COLLECTION_NAME_CONTRACT)


def test_jvm_numeric_name_contract_has_explicit_union_boundary():
    # The shared nominal checks run, but JVM cannot yet represent the mixed
    # scalar/reference unions needed by this runtime scenario.
    with pytest.raises(JVMUnsupported, match="union has incompatible runtime types"):
        transpile_jvm(NUMERIC_NAME_CONTRACT.source)


@pytest.mark.parametrize("name", ["str", "object"])
def test_jvm_nominal_optional_assignment_has_explicit_storage_boundary(name):
    # Isolate the unsupported transition: the full shared scenario contains
    # several independent JVM boundaries whose diagnostic order can change.
    with pytest.raises(JVMUnsupported, match="cannot store .* local value .*initialize"):
        transpile_jvm(f'''
            class {name}:
                def __init__(self, rank: int):
                    self.rank = rank
            def initialize(value: {name} | None) -> int:
                if value is None:
                    value = {name}(3)
                return value.rank
            def main() -> int:
                return initialize(None)
        ''')


def test_jvm_application_object_keeps_its_constructor_and_inherited_methods(tmp_path):
    source = '''
class object:
    def __init__(self, value: int):
        self.value = value
    def get(self) -> int:
        return self.value
class Child(object):
    pass
def main() -> int:
    value: object = Child(7)
    return value.get()
'''
    namespace = {}
    exec(source, namespace)
    transpile_jvm(source).write(tmp_path)
    result = subprocess.run([java(), "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == namespace["main"]() == 7
    assert result.stdout == result.stderr == ""


def test_jvm_union_reflection_has_an_explicit_representation_boundary():
    # JS/LLVM execute this shared scenario. JVM still cannot store these
    # unrelated application classes in the union's Object slot.
    with pytest.raises(JVMUnsupported, match="cannot store .* in Ljava/lang/Object; local conditional"):
        transpile_jvm(UNION_REFLECTED_ARITHMETIC_CONTRACT.source)


@pytest.mark.parametrize("contract", [FIELD_ASSIGNMENT_CONTRACT, MAPPING_ASSIGNMENT_CONTRACT,
                                     INHERITED_FIELD_ASSIGNMENT_CONTRACT, CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
                                     INHERITED_FACTORY_FIELD_CONTRACT],
                         ids=["field", "mapping", "inherited_field", "class_declared_field", "inherited_factory"])
def test_jvm_runs_shared_assignment_contract(tmp_path, contract):
    transpile_jvm(contract.source).write(tmp_path)
    result = subprocess.run([java(), "-cp", str(tmp_path), "PyjsProgram"], check=False)
    assert result.returncode == 0, contract.failure(result.returncode)


def test_unpacking_fields_keeps_the_jvm_statement_boundary():
    # JVM rejected these attribute targets before per-target shared analysis;
    # accepting their typed source does not imply a new JVM lowering contract.
    with pytest.raises(JVMUnsupported, match="unsupported JVM statement UnpackAssignment at line 5"):
        transpile_jvm(UNPACK_FIELD_CONTRACT.source)


def test_jvm_tuple_index_contract_has_explicit_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM scalar operation __getitem__"):
        transpile_jvm(TUPLE_INDEX_CONTRACT.source)


def test_jvm_literal_field_contract_has_explicit_union_storage_boundary():
    with pytest.raises(JVMUnsupported, match="union has incompatible runtime types"):
        transpile_jvm(LITERAL_FIELD_ASSIGNMENT_CONTRACT.source)


def test_jvm_property_field_override_keeps_unsupported_analysis_boundary():
    with pytest.raises(CompilationError, match="Function returns str.*NoneType, not str"):
        transpile_jvm(PROPERTY_FIELD_OVERRIDE_CONTRACT.source)


def test_jvm_nested_conditional_order(tmp_path):
    contract = NESTED_CONDITIONAL_CONTRACT
    transpile_jvm(contract.source).write(tmp_path)
    result = subprocess.run([java(), "-cp", str(tmp_path), "PyjsProgram"], check=False)
    assert result.returncode == 0, contract.failure(result.returncode)


@pytest.mark.parametrize(
    "source",
    PORTABLE_FAILURE_SOURCES.values(),
    ids=PORTABLE_FAILURE_SOURCES,
)
def test_jvm_rejects_shared_portable_numeric_failures(tmp_path, source):
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


@pytest.mark.parametrize(
    "source",
    [
        """
        def main() -> int:
            return [1][-2]
        """,
        """
        def main() -> int:
            total = 0
            for value in range(0, 3, 0):
                total = total + value
            return total
        """,
        """
        def main() -> int:
            return 1 // 0
        """,
        """
        def main() -> int:
            value = 1.0 / 0.0
            return 0
        """,
    ],
)
def test_jvm_transpiler_raises_for_invalid_runtime_operations(tmp_path, source):
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Exception" in result.stderr


def test_jvm_transpiler_executes_python_assertions(tmp_path):
    source = """\
def check(value: bool) -> None:
    assert value, "expected a true value"


def main() -> int:
    check(False)
    return 0
"""
    transpile_jvm(source, filename="assertions.py").write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "PyjsProgram$exception$AssertionError: expected a true value" in result.stderr
    assert "PyjsProgram.check(assertions.py:2)" in result.stderr


def test_jvm_application_calls_fill_immutable_literal_defaults(tmp_path):
    source = """\
class Card:
    def __init__(
        self,
        title: str = "",
        count: int = -1,
        pinned: bool = False,
    ):
        self.title = title
        self.count = count
        self.pinned = pinned

    def shifted(self, amount: int = 3) -> int:
        return self.count + amount


def add(value: int, amount: int = 4) -> int:
    return value + amount


def main() -> int:
    if Card().pinned == True:
        return 2
    if Card().pinned != False:
        return 1
    if Card(count=2).shifted() != 5:
        return 3
    return Card().shifted() + add(2)
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 8


@pytest.mark.parametrize(
    ("python_name", "jvm_name"),
    [
        ("Exception", "Exception"),
        ("ValueError", "ValueError"),
        ("AssertionError", "AssertionError"),
        ("AttributeError", "AttributeError"),
    ],
)
def test_jvm_raises_python_exception_types(tmp_path, python_name, jvm_name):
    source = f"""\
def main() -> int:
    raise {python_name}("invalid note")
"""
    transpile_jvm(source, filename="model.py").write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"PyjsProgram$exception${jvm_name}: invalid note" in result.stderr
    assert "PyjsProgram.pyjs_main(model.py:2)" in result.stderr


def test_jvm_rejects_mutable_application_defaults():
    with pytest.raises(
        JVMUnsupported,
        match="function defaults must be immutable literals",
    ):
        transpile_jvm(
            """
            def count(values: list[int] = []) -> int:
                return len(values)


            def main() -> int:
                return count()
            """
        )


def test_jvm_application_calls_bind_keywords(tmp_path):
    compilation = transpile_jvm(
        """
        def add(value: int, amount: int = 1) -> int:
            return value + amount


        def main() -> int:
            return add(2, amount=3)
        """
    )
    compilation.write(tmp_path)
    result = subprocess.run([java(), "-cp", str(tmp_path), "PyjsProgram"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 5, result.stderr


def test_jvm_runs_immediate_async_virtual_calls(tmp_path):
    source = """\
from pyjs.java import run_sync


class Repository:
    async def load(self) -> int:
        return 1


class MemoryRepository(Repository):
    async def load(self) -> int:
        return 4


async def calculate(repository: Repository) -> int:
    value = await repository.load()
    return value + 1


def main() -> int:
    return run_sync(calculate(MemoryRepository()))
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 5


def test_jvm_rejects_unconsumed_async_calls():
    with pytest.raises(
        JVMUnsupported,
        match="must be immediately awaited or passed to run_sync",
    ):
        transpile_jvm(
            """
            async def load() -> int:
                return 1


            def main() -> int:
                load()
                return 0
            """
        )


def test_jvm_runs_reference_dictionary_operations(tmp_path):
    source = """\
def identity(values: dict[str, str]) -> dict[str, str]:
    return values


def main() -> int:
    values: dict[str, str] = {"a": "one"}
    values["b"] = "two"
    if values.get("a", "bad") != "one":
        return 1
    if values.get("missing", "three") != "three":
        return 2
    if values.get("missing", None) is not None:
        return 3
    if values["b"] != "two":
        return 4
    return len(identity(values))
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 2


def test_jvm_compares_reference_identity(tmp_path):
    source = """\
class Value:
    pass


def main() -> int:
    first = Value()
    alias = first
    other = Value()
    if first is not alias:
        return 1
    if first is other:
        return 2
    return 0
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 0


def test_jvm_dictionary_subscript_rejects_a_missing_key(tmp_path):
    source = """\
def main() -> int:
    values: dict[str, str] = {}
    values["missing"]
    return 0
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "$exception$KeyError: 'missing'" in result.stderr


def test_jvm_dictionary_rejects_primitive_keys():
    with pytest.raises(
        JVMUnsupported,
        match="dictionaries require reference keys and reference or scalar values",
    ):
        transpile_jvm(
            """
            def main() -> int:
                values: dict[int, int] = {1: 42}
                return values[1]
            """
        )


def test_jvm_retains_classes_referenced_only_by_fields():
    source = """\
class Item:
    pass


class State:
    def __init__(self):
        self.items: list[Item] = []
        self.listeners: list[callable] = []


def main() -> int:
    state = State()
    return len(state.items) + len(state.listeners)
"""
    compilation = transpile_jvm(source)

    assert "PyjsProgram$Item" in compilation.classes


def test_jvm_transpiler_emits_imported_functions_and_classes(tmp_path, monkeypatch):
    module_name = "jvm_imported_helper"
    helper = tmp_path / f"{module_name}.py"
    helper.write_text(
        """\
class Offset:
    def __init__(self, value: int):
        self.value = value

    def apply(self, value: int) -> int:
        return value + self.value


def calculate(value: int) -> int:
    return Offset(2).apply(value)
"""
    )
    source = f"""\
from {module_name} import calculate


def main() -> int:
    return calculate(40)
"""
    monkeypatch.syspath_prepend(tmp_path)
    sys.modules.pop(module_name, None)
    try:
        compilation = transpile_jvm(
            source,
            filename=str(tmp_path / "entry.py"),
            module_name="jvm_import_entry",
        )
    finally:
        sys.modules.pop(module_name, None)
    compilation.write(tmp_path / "classes")

    assert "PyjsProgram$module$jvm_imported_helper" in compilation.classes
    assert "PyjsProgram$module$jvm_imported_helper$Offset" in compilation.classes
    result = subprocess.run(
        [java(), "-cp", str(tmp_path / "classes"), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 42


def test_jvm_transpiler_emits_junit_android_test_wrappers(tmp_path, monkeypatch):
    module_name = "jvm_test_module"
    tests = tmp_path / f"{module_name}.py"
    tests.write_text(
        """\
def test_answer() -> None:
    assert 40 + 2 == 42
"""
    )
    source = f"""\
from {module_name} import test_answer as __pyjs_test_0


def main() -> int:
    return 0
"""
    monkeypatch.syspath_prepend(tmp_path)
    sys.modules.pop(module_name, None)
    try:
        compilation = transpile_jvm(
            source,
            filename=str(tmp_path / "android_tests.py"),
            module_name="jvm_test_entry",
            root_names=("__pyjs_test_0",),
            tests=(
                JVMTest(
                    "test_android.py::test_answer",
                    module_name,
                    "test_answer",
                ),
            ),
            test_sdk=35,
        )
    finally:
        sys.modules.pop(module_name, None)

    assert len(compilation.tests) == 1
    compiled = compilation.tests[0]
    assert compiled.nodeid == "test_android.py::test_answer"
    assert compiled.class_name == "PyjsProgram$Tests"
    assert compiled.method_name == "test_0_test_answer"
    test_class = read_jvm_class(compilation.classes[compiled.class_name])
    assert test_class.annotations[0].descriptor == "Lorg/junit/runner/RunWith;"
    assert test_class.annotations[0].values == (
        (
            "value",
            "Landroidx/test/ext/junit/runners/AndroidJUnit4;",
        ),
    )
    assert test_class.annotations[1].descriptor == ("Lorg/robolectric/annotation/Config;")
    assert test_class.annotations[1].values == (("sdk", (35,)),)
    method = test_class.declared_methods(compiled.method_name)[0]
    assert method.descriptor == "()V"
    assert method.access & 0x0001
    assert method.annotations[0].descriptor == "Lorg/junit/Test;"
    teardown = test_class.declared_methods("pyjs_close_activity")[0]
    assert teardown.annotations[0].descriptor == "Lorg/junit/After;"


def test_jvm_transpiler_preserves_python_string_operations(tmp_path):
    transpile_jvm(STRING_SOURCE).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 17


def test_jvm_string_length_and_indexing_use_unicode_code_points(tmp_path):
    source = """\
def main() -> int:
    value = "a😀z"
    if len(value) != 3:
        return 1
    if value[1] != "😀":
        return 2
    if value[-1] != "z":
        return 3
    if "ab" * 3 != "ababab":
        return 4
    if 2 * "😀" != "😀😀":
        return 5
    if "x" * -1 != "":
        return 6
    return len(value[1]) + 6
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 7


def test_jvm_string_helpers_preserve_shared_parser_semantics(tmp_path):
    source = """\
from pyjs import JS

LIMIT: JS = 9


def matches(value: str | None) -> bool:
    return value == "trimmed"


def main() -> int:
    values = [" one ", "two"]
    if ",".join(values) != " one ,two":
        return 1
    if "  trimmed  ".strip() != "trimmed":
        return 2
    if "trail  ".rstrip() != "trail":
        return 3
    if not "prefix-value".startswith("prefix"):
        return 4
    if not "prefix-value".endswith("value"):
        return 5
    if "fix" not in "prefix-value":
        return 6
    if int("42") != 42 or min(7, 3) != 3 or max(7, 3) != 7:
        return 7
    if ("" or "fallback") != "fallback":
        return 8
    if not matches("trimmed") or matches(None):
        return 9
    return LIMIT + 1
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 10


def test_jvm_isinstance_uses_application_class_hierarchy(tmp_path):
    source = """\
class Base:
    pass


class Child(Base):
    def __init__(self):
        self.value = 4


def child_value(value: Base) -> int:
    if isinstance(value, Child):
        return value.value
    return 0


def main() -> int:
    value = Child()
    if not isinstance(value, Child):
        return 1
    if not isinstance(value, Base):
        return 2
    values: list[Base] = [Base(), Child()]
    return child_value(values[1]) + 1
"""
    transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 5


@pytest.mark.parametrize("ascii_stdout", [False, True])
def test_jvm_transpiler_writes_a_unicode_string_entry_point(tmp_path, ascii_stdout):
    transpile_jvm(STRING_OUTPUT_SOURCE).write(tmp_path)
    entry = "PyjsProgram"
    if ascii_stdout:
        # Exercise a non-UTF-8 PrintStream on every OS, not only Windows.
        launcher = tmp_path / "AsciiOutput.java"
        launcher.write_text('''
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
class AsciiOutput {
    public static void main(String[] args) {
        System.setOut(new PrintStream(System.out, true, StandardCharsets.US_ASCII));
        PyjsProgram.main(args);
    }
}
''')
        entry = str(launcher)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), entry],
        check=True,
        capture_output=True,
    )

    assert result.stdout == "café 😀 \x00: 42 ✓".encode()


def test_jvm_transpiler_uses_jvm_inheritance_and_virtual_dispatch(tmp_path):
    compilation = transpile_jvm(INHERITANCE_SOURCE)
    compilation.write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )
    assert result.returncode == 22

    puppy = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(tmp_path / "PyjsProgram$Puppy.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        puppy.stdout
        == """\
Compiled from "_pyjs_java_.py"
public final class PyjsProgram$Puppy extends PyjsProgram$Dog {
  public PyjsProgram$Puppy();
  public long reward();
}
"""
    )


def test_jvm_transpiler_preserves_python_signed_divmod(tmp_path):
    transpile_jvm(INTEGER_SEMANTICS_SOURCE).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 29


def test_jvm_native_declarations_validate_and_expose_one_record():
    assert backend_metadata(current_time_millis, "jvm", "owner") == ("java/lang/System")
    assert backend_metadata(current_time_millis, "jvm", "name") == ("currentTimeMillis")
    assert backend_metadata(current_time_millis, "jvm", "invocation") == "static"

    with pytest.raises(TypeError, match="internal name"):
        jvm.native("java.lang.System")(lambda: None)
    with pytest.raises(TypeError, match="internal name"):
        jvm.native("bad//Owner")(lambda: None)
    with pytest.raises(TypeError, match="not supported"):
        jvm.native("java/lang/Object", invocation="interface")(lambda: None)
    with pytest.raises(TypeError, match="require a class"):
        jvm.native("java/lang/Runnable", interface=True)(lambda: None)
    with pytest.raises(TypeError, match="non-empty string"):
        jvm.field(name="")
    with pytest.raises(TypeError, match="must be a bool"):
        jvm.field(writable=1)

    field = jvm.field(name="nativeName", writable=False)
    assert field.name == "nativeName"
    assert field.writable is False


def test_jvm_transpiler_calls_a_native_runtime_declaration(tmp_path):
    transpile_jvm(NATIVE_DECLARATION_SOURCE).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 31


def test_jvm_transpiler_constructs_and_calls_a_native_object(tmp_path):
    transpile_jvm(NATIVE_OBJECT_SOURCE).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=True,
        capture_output=True,
    )

    assert result.stdout == "native JVM ✓".encode()


def test_jvm_native_constructor_rebinds_keyword_arguments(tmp_path):
    transpile_jvm(NATIVE_CONSTRUCTOR_SOURCE).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=True,
        capture_output=True,
    )

    assert result.stdout == "argument ✓".encode()


def test_jvm_native_calls_reject_keyword_arguments_instead_of_ignoring_them():
    with pytest.raises(
        JVMUnsupported,
        match="native calls do not yet support keyword arguments",
    ):
        transpile_jvm(
            """
            from pyjs import jvm
            from pyjs.java import i32

            @jvm.native("java/lang/Integer", name="rotateLeft")
            def rotate(value: i32, distance: i32 = 3) -> i32:
                return value

            def main() -> int:
                return rotate(1, distance=4)
            """
        )


def test_jvm_native_calls_use_exact_primitive_abi_widths(tmp_path):
    output = write_class(tmp_path, NATIVE_PRIMITIVE_SOURCE)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 37, result.stderr

    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "java/lang/Integer.rotateLeft:(II)I" in bytecode
    assert "java/lang/Math.round:(F)I" in bytecode
    assert "java/lang/Math.sqrt:(D)D" in bytecode
    assert "java/lang/Float.intBitsToFloat:(I)F" in bytecode
    assert 'java/lang/StringBuilder."<init>":(I)V' in bytecode
    assert "java/lang/StringBuilder.append:(I)Ljava/lang/StringBuilder;" in bytecode


def test_jvm_native_calls_accept_shared_signed_integer_widths(tmp_path):
    output = write_class(
        tmp_path,
        """
        from pyjs import int8, int16
        from pyjs import jvm

        @jvm.native("java/lang/Byte", name="parseByte")
        def parse_byte(value: str) -> int8:
            return int8(value)

        @jvm.native("java/lang/Short", name="parseShort")
        def parse_short(value: str) -> int16:
            return int16(value)

        def main() -> int:
            return int16(parse_byte("-5")) + parse_short("42")
        """,
    )

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 37
    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "parseByte:(Ljava/lang/String;)B" in bytecode
    assert "parseShort:(Ljava/lang/String;)S" in bytecode


def test_jvm_native_unsigned_results_widen_to_python_int(tmp_path):
    output = write_class(
        tmp_path,
        """
        from pyjs import uint32
        from pyjs import jvm

        @jvm.native("java/lang/Integer", name="parseUnsignedInt")
        def parse_unsigned(value: str) -> uint32:
            return uint32(value)

        def main() -> int:
            if parse_unsigned("4294967295") == 4294967295:
                return 37
            return 1
        """,
    )

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 37
    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "parseUnsignedInt:(Ljava/lang/String;)I" in bytecode


def test_jvm_generated_code_uses_shared_numeric_storage_formats(tmp_path):
    output = write_class(
        tmp_path,
        """
        from pyjs import float32, float64, int8, int16, int32, int64

        class Reading:
            value: int16

            def __init__(self, value: int16) -> None:
                self.value = value

        def adjust(value: int8) -> int16:
            adjusted: int32 = int32(value + 1)
            return int16(adjusted)

        def half(value: float32) -> float64:
            return float64(value / float32(2.0))

        def wide(value: int64) -> int64:
            return value + 1

        def narrow(value: int64) -> int64:
            return value - 1

        def identity(value: int64) -> int64:
            return value

        def wrap(value: int8) -> int8:
            return (value + 30) * 3

        def main() -> int:
            if half(float32(5.0)) != 2.5:
                return 1
            if wide(9007199254740992) != 9007199254740993:
                return 2
            if wide(9223372036854775807) >= 0:
                return 3
            if narrow(wide(9223372036854775807)) != 9223372036854775807:
                return 4
            if identity(-9223372036854775808) >= 0:
                return 5
            if wrap(100) != -122:
                return 6
            if int8(130.9) != -126:
                return 7
            return Reading(adjust(36)).value
        """,
    )

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 37
    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    reading = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(tmp_path / "PyjsProgram$Reading.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "static short adjust(byte);" in bytecode
    assert "static double half(float);" in bytecode
    assert "static long wide(long);" in bytecode
    assert "public short value;" in reading
    assert "public void pyjs_init(short);" in reading


def test_jvm_generated_method_calls_use_numeric_storage_formats(tmp_path):
    output = write_class(
        tmp_path,
        """
        from pyjs import int32

        class Counter:
            value: int32

            def __init__(self, value: int32) -> None:
                self.value = value

            def add(self, delta: int32) -> int32:
                return int32(self.value + delta)

        def main() -> int:
            return Counter(int32(19)).add(int32(18))
        """,
    )

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 37, result.stderr
    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "PyjsProgram$Counter.add:(I)I" in bytecode


def test_jvm_shared_unsigned_formats_zero_extend_storage_values(tmp_path):
    output = write_class(
        tmp_path,
        """
        from pyjs import uint8, uint16, uint32

        class Reading:
            value: uint16

            def __init__(self, value: uint16) -> None:
                self.value = value

        def widen(value: uint8) -> uint32:
            return uint32(value)

        def main() -> int:
            if widen(-1) != 255:
                return 1
            if Reading(-1).value != 65535:
                return 2
            return 37
        """,
    )

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
    )

    assert result.returncode == 37
    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    reading = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(tmp_path / "PyjsProgram$Reading.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "static int widen(byte);" in bytecode
    assert "public char value;" in reading
    assert "public void pyjs_init(char);" in reading


def test_jvm_tracebacks_report_python_source_functions_and_lines(tmp_path):
    compilation = transpile_jvm(
        TRACEBACK_SOURCE,
        filename="calculator_android.py",
    )
    compilation.write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "PyjsProgram$exception$ZeroDivisionError" in result.stderr
    assert "PyjsProgram.divide(calculator_android.py:3)" in result.stderr
    assert "PyjsProgram.calculate(calculator_android.py:7)" in result.stderr
    assert "PyjsProgram.pyjs_main(calculator_android.py:11)" in result.stderr


def test_jvm_native_static_and_instance_fields_use_exact_descriptors(tmp_path):
    output = write_class(tmp_path, NATIVE_FIELD_SOURCE)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 12, result.stderr

    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "java/awt/Point.x:I" in bytecode
    assert "java/awt/Point.y:I" in bytecode
    assert "java/lang/Integer.MAX_VALUE:I" in bytecode


def test_jvm_generated_callback_implements_and_invokes_native_interface(tmp_path):
    compilation = transpile_jvm(NATIVE_INTERFACE_SOURCE)
    compilation.write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 40, result.stderr

    callback = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(tmp_path / "PyjsProgram$Callback.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "implements java.lang.Runnable" in callback

    main_bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(tmp_path / "PyjsProgram.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "InterfaceMethod java/lang/Runnable.run:()V" in main_bytecode


def test_jvm_generated_class_extends_and_overrides_native_superclass(tmp_path):
    compilation = transpile_jvm(NATIVE_SUPERCLASS_SOURCE)
    compilation.write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 43, result.stderr

    worker = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(tmp_path / "PyjsProgram$Worker.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "extends java.lang.Thread" in worker
    assert 'java/lang/Thread."<init>":()V' in worker
    assert "java/lang/Thread.run:()V" in worker


def test_jvm_double_arithmetic_and_runtime_conversions_execute(tmp_path):
    output = write_class(tmp_path, FLOAT_ARITHMETIC_SOURCE)

    result = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 44, result.stderr

    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "java/lang/Double.parseDouble:(Ljava/lang/String;)D" in bytecode
    assert "java/lang/Double.toString:(D)Ljava/lang/String;" in bytecode


def test_jvm_transpiler_requires_a_valid_class_name():
    with pytest.raises(ValueError, match="valid identifiers"):
        transpile_jvm("def main() -> int: return 0", class_name="bad//name")


def test_jvm_boolean_operators_preserve_typed_results(tmp_path):
    output = transpile_jvm(
        """
def both(left: bool, right: bool) -> bool:
    return left and right


def either(left: bool, right: bool) -> bool:
    return left or right


def main() -> int:
    if both(True, True) and not both(True, False):
        if either(False, True) and not either(False, False):
            return 47
    return 1
"""
    ).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(output.parent), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 47, result.stderr


def test_jvm_compilation_writes_package_directories(tmp_path):
    path = transpile_jvm(
        "def main() -> int: return 0",
        class_name="org/pyjs/example/PyjsProgram",
    ).write(tmp_path)

    assert path == tmp_path / "org/pyjs/example/PyjsProgram.class"
    assert path.is_file()


def test_jvm_rejects_an_incompatible_virtual_override():
    with pytest.raises(JVMUnsupported, match="must preserve the base"):
        transpile_jvm(
            """
class Base:
    def choose(self, value: int) -> int:
        return 1


class Child(Base):
    def choose(self, value: bool) -> int:
        return 2 if value else 3


def call(value: Base) -> int:
    return value.choose(256)


def main() -> int:
    return call(Child())
"""
        )


@pytest.mark.parametrize(
    "method",
    [
        "pass",
        "def run(self, value: int) -> None:\n        pass",
    ],
)
def test_jvm_rejects_missing_or_incompatible_interface_methods(method):
    source = f"""
from pyjs import jvm


@jvm.native("java/lang/Runnable", interface=True)
class Runnable:
    def run(self) -> None:
        pass


@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self, target: Runnable) -> None:
        pass

    def run(self) -> None:
        pass


class Callback(Runnable):
    {method}


def main() -> int:
    Thread(Callback()).run()
    return 0
"""

    with pytest.raises(JVMUnsupported, match="interface|does not implement"):
        transpile_jvm(source)


def test_jvm_declares_enough_stack_for_wide_calls(tmp_path):
    names = [f"value_{index}" for index in range(40)]
    parameters = ", ".join(f"{name}: int" for name in names)
    arguments = ", ".join(str(index) for index in range(40))
    source = (
        f"def wide({parameters}) -> int:\n"
        "    return value_39\n\n\n"
        "def main() -> int:\n"
        f"    return wide({arguments})\n"
    )
    output = transpile_jvm(source).write(tmp_path)

    result = subprocess.run(
        [java(), "-Xverify:all", "-cp", str(output.parent), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 39, result.stderr


def test_jvm_ranges_stop_when_fixed_width_advancement_overflows(tmp_path):
    output = transpile_jvm(
        """
def main() -> int:
    count = 0
    for value in range(9223372036854775806, 9223372036854775807, 2):
        count = count + 1
    lowest = -9223372036854775807 - 1
    for value in range(lowest + 1, lowest, -2):
        count = count + 1
    return count
"""
    ).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(output.parent), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2, result.stderr


def test_jvm_traps_the_unrepresentable_fixed_width_quotient(tmp_path):
    output = transpile_jvm(
        """
def main() -> int:
    lowest = -9223372036854775807 - 1
    return lowest // -1
"""
    ).write(tmp_path)

    result = subprocess.run(
        [java(), "-cp", str(output.parent), "PyjsProgram"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "PyjsProgram$exception$OverflowError" in result.stderr


def test_jvm_writes_declared_writable_static_fields(tmp_path):
    output = transpile_jvm(
        """
from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.java import i32


@jvm.native("example/Mutable")
class Mutable:
    value: ClassVar[Annotated[i32, jvm.field()]] = 0


def main() -> int:
    Mutable.value = 7
    return 0
"""
    ).write(tmp_path)

    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "putstatic     #" in bytecode
    assert "example/Mutable.value:I" in bytecode


def test_jvm_subclasses_inherit_native_instance_fields(tmp_path):
    compilation = transpile_jvm(
        """
from typing import Annotated

from pyjs import jvm


@jvm.native("example/NativeBase")
class NativeBase:
    value: Annotated[str, jvm.field(writable=False)]

    def __init__(self) -> None:
        pass


class Child(NativeBase):
    def __init__(self) -> None:
        super().__init__()

    def read(self) -> str:
        return self.value


def main() -> int:
    Child().read()
    return 0
"""
    )
    compilation.write(tmp_path)

    bytecode = subprocess.run(
        [
            java(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(tmp_path / "PyjsProgram$Child.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "example/NativeBase.value:Ljava/lang/String;" in bytecode
