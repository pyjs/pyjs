import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.classpath import read_jvm_class
from tests.backend_semantics import SCALAR_LIST_EQUALITY_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_scalar_list_equality(tmp_path):
    assert_matches_python(SCALAR_LIST_EQUALITY_CONTRACT.source, tmp_path)


def test_list_equality_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(SCALAR_LIST_EQUALITY_CONTRACT.source, tmp_path)


@pytest.mark.parametrize(("kind", "first", "second"), [
    ("str", '"snow"', '"雪"'),
    ("str | None", "None", '"snow"'),
    ("int", "9007199254740993", "-9223372036854775808"),
    ("bool", "True", "False"),
])
def test_equality_uses_values_and_logical_length_after_mutations(tmp_path, kind, first, second):
    assert_matches_python(f'''
def main() -> int:
    left: list[{kind}] = [{first}]
    right: list[{kind}] = [{first}]
    assert left.__eq__(right) and not left.__ne__(right)
    for index in range(12):
        right.append({second})
    for index in range(12):
        right.pop()
    assert left == right
    assert left == right.copy()
    right[0] = {second}
    assert left != right and not left.__eq__(right)
    left[0] = {second}
    assert left == right
    return 42
''', tmp_path)


@pytest.mark.parametrize("operation", ["==", "!=", "__eq__", "__ne__"])
def test_equality_evaluates_each_operand_once_in_order(tmp_path, operation):
    expression = (f"left(events).{operation}(right(events))" if operation.startswith("__")
                  else f"left(events) {operation} right(events)")
    assert_text_matches_python(f'''
def left(events: list[str]) -> list[str]:
    events.append("left")
    return ["same"]
def right(events: list[str]) -> list[str]:
    events.append("right")
    return ["".join(["sa", "me"])]
def main() -> str:
    events: list[str] = []
    result = {expression}
    return ",".join(events) + ":" + str(result)
''', tmp_path)


@pytest.mark.parametrize(("left", "right"), [
    ("[1.0]", "[1.0]"), ("[1]", "[True]"), ("[1]", "[1.0]"),
    ("[[1]]", "[[1]]"), ("[1]", "None"), ("[1]", "(1,)"),
])
def test_unsupported_equality_has_located_diagnostic(left, right):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f"def main() -> bool:\n    return {left} == {right}\n", filename="equality.py")
    assert str(caught.value) == (
        "JVM list equality requires matching integer, boolean or string item storage "
        "at line 2 while compiling equality.main")


def test_equality_helper_is_only_emitted_once_when_used():
    compilation = transpile_jvm('''
def main() -> int:
    a = [1]
    b = [2]
    return int(a == b or a != b or a.__eq__(b))
''')
    owner = read_jvm_class(compilation.classes["PyjsProgram$list$J"])
    assert [(method.name, method.descriptor) for method in owner.methods
            if method.name == "same_items"] == [("same_items", "(LPyjsProgram$list$J;)Z")]
    unused = transpile_jvm("def main() -> int:\n    return len([1])\n")
    owner = read_jvm_class(unused.classes["PyjsProgram$list$J"])
    assert not any(method.name == "same_items" for method in owner.methods)
