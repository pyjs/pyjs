import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.classpath import read_jvm_class
from tests.backend_semantics import (
    INTEGER_LIST_MEMBERSHIP_CONTRACT,
    STRING_DICTIONARY_MEMBERSHIP_CONTRACT,
)
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


@pytest.mark.parametrize("contract", [INTEGER_LIST_MEMBERSHIP_CONTRACT, STRING_DICTIONARY_MEMBERSHIP_CONTRACT])
def test_shared_membership_contract(tmp_path, contract):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("contract", [INTEGER_LIST_MEMBERSHIP_CONTRACT, STRING_DICTIONARY_MEMBERSHIP_CONTRACT])
def test_membership_compiles_to_android_dex(tmp_path, contract):
    assert_compiles_to_android_dex(contract.source, tmp_path)


@pytest.mark.parametrize(("annotation", "value", "descriptor"), [
    ("int", "42", "(J)Z"),
    ("bool", "False", "(Z)Z"),
])
def test_list_search_helper_is_emitted_once_on_demand(annotation, value, descriptor):
    compilation = transpile_jvm(f'''
def main() -> int:
    values: list[{annotation}] = [{value}]
    return int({value} in values) + int(values.__contains__({value}))
''')
    helper = read_jvm_class(compilation.classes[f"PyjsProgram$list${descriptor[1]}"])
    assert [(method.name, method.descriptor) for method in helper.methods] == [
        ("<init>", "()V"),
        ("append", f"({descriptor[1]})V"),
        ("get", f"(J){descriptor[1]}"),
        ("set", f"(J{descriptor[1]})V"),
        ("insert", f"(J{descriptor[1]})V"),
        ("contains", descriptor),
    ]


@pytest.mark.parametrize(("kind", "needle", "contents"), [
    ("int", "42", "[-9, 0, 42]"),
    ("bool", "False", "[True, False]"),
])
def test_list_membership_observes_logical_length_and_mutation(tmp_path, kind, needle, contents):
    assert_matches_python(f'''
def main() -> int:
    values: list[{kind}] = []
    assert {needle} not in values
    for value in {contents}:
        values.append(value)
    assert {needle} in values
    assert values.__contains__({needle})
    values[-1] = values[0]
    assert {needle} not in values
    return 42
''', tmp_path)


@pytest.mark.parametrize(("annotation", "needle", "container"), [
    ("str", '"key"', '"prefix-key"'),
    ("list[int]", "42", "[41, 42]"),
    ("list[bool]", "True", "[False, True]"),
    ("dict[str, str]", '"key"', '{"key": ""}'),
])
@pytest.mark.parametrize("operation", ["in", "not in", "explicit"])
def test_membership_operand_order(tmp_path, annotation, needle, container, operation):
    item = "bool" if "bool" in annotation else "int" if "int" in annotation else "str"
    expression = ("container(events).__contains__(needle(events))" if operation == "explicit"
                  else f"needle(events) {operation} container(events)")
    assert_text_matches_python(f'''
def needle(events: list[str]) -> {item}:
    events.append("needle")
    return {needle}

def container(events: list[str]) -> {annotation}:
    events.append("container")
    return {container}

def main() -> str:
    events: list[str] = []
    found = {expression}
    return "|".join(events) + ":" + str(found)
''', tmp_path)


@pytest.mark.parametrize("operation", ["in", "not in", "explicit"])
def test_membership_with_user_protocol_preserves_order(tmp_path, operation):
    expression = ("container(events).__contains__(needle(events))" if operation == "explicit"
                  else f"needle(events) {operation} container(events)")
    assert_text_matches_python(f'''
class Values:
    def __init__(self, events: list[str]):
        self.events = events

    def __contains__(self, value: int) -> bool:
        self.events.append("contains")
        return value == 42

def needle(events: list[str]) -> int:
    events.append("needle")
    return 42

def container(events: list[str]) -> Values:
    events.append("container")
    return Values(events)

def main() -> str:
    events: list[str] = []
    found = {expression}
    return "|".join(events) + ":" + str(found)
''', tmp_path)


@pytest.mark.parametrize("operation", ["in", "not in", "explicit"])
def test_native_membership_argument_is_evaluated_once(tmp_path, operation):
    expression = ("container(events).__contains__(needle(events))" if operation == "explicit"
                  else f"needle(events) {operation} container(events)")
    assert_text_matches_python(f'''
from pyjs import jvm

@jvm.native("java/lang/String")
class Prefix:
    def __init__(self, text: str):
        self.text = text

    @jvm.native("java/lang/String", name="startsWith", invocation="virtual")
    def __contains__(self, needle: str) -> bool:
        return self.text.startswith(needle)

def needle(events: list[str]) -> str:
    events.append("needle")
    return "pre"

def container(events: list[str]) -> Prefix:
    events.append("container")
    return Prefix("prefix")

def main() -> str:
    events: list[str] = []
    found = {expression}
    return "|".join(events) + ":" + str(found)
''', tmp_path)


@pytest.mark.parametrize("failure", ["needle", "container"])
@pytest.mark.parametrize("explicit", [False, True])
def test_membership_failure_stops_later_operand_evaluation(tmp_path, failure, explicit):
    expression = ("container(events).__contains__(needle(events))" if explicit
                  else "needle(events) in container(events)")
    assert_text_matches_python(f'''
def needle(events: list[str]) -> str:
    events.append("needle")
    if {failure == 'needle'}:
        raise ValueError("needle failed")
    return "key"

def container(events: list[str]) -> str:
    events.append("container")
    if {failure == 'container'}:
        raise ValueError("container failed")
    return "key"

def main() -> str:
    events: list[str] = []
    try:
        found = {expression}
        events.append(str(found))
    except ValueError as error:
        events.append(str(error))
    return "|".join(events)
''', tmp_path)


@pytest.mark.parametrize(("key_type", "first", "second"), [
    ("str | None", '"key"', '"other"'),
    ("bool | None", "True", "False"),
])
def test_dictionary_membership_boxes_nullable_keys_and_ignores_values(tmp_path, key_type, first, second):
    assert_matches_python(f'''
def main() -> int:
    values: dict[{key_type}, str | None] = {{None: "present", {first}: None}}
    assert None in values
    assert {first} in values
    assert {second} not in values
    assert values.__contains__({first})
    assert not values.__contains__({second})
    values[{second}] = "later"
    assert {second} in values
    return 42
''', tmp_path)


@pytest.mark.parametrize(("annotation", "contents", "needle"), [
    ("str", '["x"]', '"x"'),
    ("float", "[1.5]", "1.5"),
    ("int", "[1]", "True"),
])
def test_unsupported_list_membership_has_focused_diagnostic(annotation, contents, needle):
    source = f'def main() -> int:\n    values: list[{annotation}] = {contents}\n    return int({needle} in values)\n'
    with pytest.raises(JVMUnsupported) as error:
        transpile_jvm(source, filename="membership.py")
    assert str(error.value) == (
        "JVM list membership requires matching integer or boolean items "
        "at line 3 while compiling membership.main"
    )


def test_integer_membership_keeps_large_and_normalized_values(tmp_path):
    assert_matches_python('''
from pyjs import int8, int64

def main() -> int:
    wide = [int64(9007199254740993), int64(-9223372036854775808)]
    small = [int8(255), int8(128)]
    assert int64(9007199254740993) in wide
    assert int64(9007199254740992) not in wide
    assert int64(-9223372036854775808) in wide
    assert int8(-1) in small
    assert int8(-128) in small
    assert int8(127) not in small
    return 42
''', tmp_path)
