import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.classpath import read_jvm_class
from tests.backend_semantics import REFERENCE_TUPLE_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
    run_jvm,
)


def test_shared_reference_tuple_contract(tmp_path):
    assert_matches_python(REFERENCE_TUPLE_CONTRACT.source, tmp_path)


def test_reference_tuple_contract_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(REFERENCE_TUPLE_CONTRACT.source, tmp_path)


def test_variadic_tuple_descriptors_do_not_use_fixed_tuple_classes():
    compilation = transpile_jvm('''
def values() -> tuple[str, ...]:
    return ("a", "b")

def main() -> int:
    return len(values())
''')
    assert not any("$tuple$" in name for name in compilation.classes)
    methods = read_jvm_class(compilation.classes["PyjsProgram"]).methods
    assert [(method.name, method.descriptor) for method in methods] == [
        ("pyjs_main", "()J"), ("values", "()[Ljava/lang/String;"),
        ("main", "([Ljava/lang/String;)V"),
    ]


def test_literal_return_parameter_field_and_iteration(tmp_path):
    assert_text_matches_python('''
class Row:
    def __init__(self, items: tuple[str, ...]):
        self.items = items

def make(empty: bool) -> tuple[str, ...]:
    if empty:
        return ()
    return ("first", "second", "third")

def describe(items: tuple[str, ...]) -> str:
    result = ""
    for item in items:
        result += item + ";"
    return result

def main() -> str:
    row = Row(make(False))
    assert len(row.items) == 3
    assert row.items.__len__() == 3
    assert row.items[0] == "first"
    assert row.items[-1] == "third"
    assert row.items[True] == "second"
    assert row.items[False] == "first"
    alias = row.items
    assert alias is row.items
    row.items = make(True)
    assert row.items is not alias
    assert len(row.items) == 0
    return describe(alias) + describe(row.items)
''', tmp_path)


def test_deferred_tuple_local_annotation(tmp_path):
    assert_text_matches_python('''
from typing import cast

def make() -> tuple[object, ...]:
    return (cast(object, "value"),)

def main() -> str:
    values: tuple[object, ...]
    values = make()
    return cast(str, values[0])
''', tmp_path)


@pytest.mark.parametrize("index", [-2**63, -4, -3, -1, 0, 2, 3, 2**63 - 1])
@pytest.mark.parametrize("contents", ['()', '("a", "b", "c")'])
def test_checked_indexing_matches_python(tmp_path, contents, index):
    assert_text_matches_python(f'''
def select(items: tuple[str, ...], index: int) -> str:
    try:
        return items[index]
    except IndexError:
        return "out of bounds"

def main() -> str:
    items: tuple[str, ...] = {contents}
    return select(items, {index})
''', tmp_path)


def test_nested_reference_items_keep_identity(tmp_path):
    assert_text_matches_python('''
class Item:
    def __init__(self, label: str):
        self.label = label

def main() -> str:
    item = Item("original")
    values: tuple[Item | None, ...] = (item, None, item)
    outer: tuple[tuple[Item | None, ...], ...] = (values, values)
    assert outer[0] is values
    assert values[0] is item
    assert values[-1] is item
    assert values[1] is None
    item.label = "changed"
    result = ""
    for row in outer:
        for value in row:
            if value is not None:
                result += value.label
    return result
''', tmp_path)


def test_tuple_access_evaluates_receiver_then_index_once(tmp_path):
    assert_text_matches_python('''
def make(events: list[str]) -> tuple[str, ...]:
    events.append("receiver")
    return ("a", "b")

def index(events: list[str]) -> int:
    events.append("index")
    return -1

def main() -> str:
    events: list[str] = []
    assert make(events)[index(events)] == "b"
    assert len(events) == 2
    return events[0] + ":" + events[1]
''', tmp_path)


def test_nullable_boolean_reference_storage_and_object_views(tmp_path):
    assert_text_matches_python('''
from typing import cast

def main() -> str:
    flags: tuple[bool | None, ...] = (True, None, False)
    assert flags[0] == True
    assert flags[1] is None
    assert flags[2] == False
    words: tuple[object, ...] = (cast(object, "first"), None, cast(object, "last"))
    assert words[1] is None
    return cast(str, words[-1])
''', tmp_path)


def test_plain_object_equality_is_unchanged(tmp_path):
    assert_text_matches_python('''
from typing import cast

class Item:
    pass

def equal(left: object, right: object) -> bool:
    return left == right

def different(left: object, right: object) -> bool:
    return left != right

def main() -> str:
    item = Item()
    assert equal(cast(object, item), cast(object, item))
    assert different(cast(object, item), cast(object, Item()))
    assert equal(cast(object, "same"), cast(object, "same"))
    assert not equal(cast(object, "left"), cast(object, "right"))
    assert equal(None, None)
    return "ok"
''', tmp_path)


def test_iteration_cleanup_and_nested_loop_state(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    values: tuple[str, ...] = ("a", "skip", "b", "stop", "bad")
    empty: tuple[str, ...] = ()
    result = ""
    for value in values:
        try:
            if value == "skip":
                continue
            if value == "stop":
                break
            for suffix in values:
                if suffix == "skip":
                    break
                result += value + suffix
        finally:
            result += ";"
    else:
        result += "wrong"
    for value in empty:
        result += "wrong"
    else:
        result += "empty"
    return result
''', tmp_path)


@pytest.mark.parametrize(("expression", "left", "right"), [
    ("left == right", "values", "values"),
    ("left != right", "values", "values"),
    ("left == right", "values", '"plain"'),
    ("left == right", '"plain"', "values"),
])
def test_erased_tuple_equality_is_rejected_at_runtime(tmp_path, expression, left, right):
    actual = run_jvm(f'''
from typing import cast

def compare(left: object, right: object) -> str:
    try:
        result = {expression}
        return "unexpected:" + str(result)
    except TypeError as error:
        return str(error)

def main() -> str:
    values: tuple[str, ...] = ("a",)
    return compare(cast(object, {left}), cast(object, {right}))
''', tmp_path)
    assert actual.returncode == 0, actual.stderr
    assert actual.stderr == ""
    assert actual.stdout == "JVM reference-array equality is not implemented", actual.stdout


@pytest.mark.parametrize(("body", "message"), [
    ("return values == values", "JVM variadic tuple __eq__ is not implemented"),
    ("return values != values", "JVM variadic tuple __ne__ is not implemented"),
    ("return values[1:] is values", "JVM variadic tuple __slice__ is not implemented"),
    ("return values.__mul__(2) is values", "JVM variadic tuple __mul__ is not implemented"),
    ("return values.__contains__('a')", "JVM variadic tuple __contains__ is not implemented"),
])
def test_unsupported_operations_have_focused_diagnostics(body, message):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''
def main() -> bool:
    values: tuple[str, ...] = ("a", "b")
    {body}
''', filename="tuple_boundary.py")
    assert str(caught.value) == message + " at line 3 while compiling tuple_boundary.main"


@pytest.mark.parametrize(("annotation", "value"), [
    ("int", "1"), ("float", "1.5"), ("bool", "True"),
])
def test_primitive_items_are_not_silently_given_a_fixed_tuple_layout(annotation, value):
    with pytest.raises(JVMUnsupported, match="JVM variadic tuples require reference items"):
        transpile_jvm(f'''
def main() -> int:
    items: tuple[{annotation}, ...] = ({value},)
    return len(items)
''')


def test_variadic_tuple_iteration_cannot_use_fixed_tuple_field_unpacking():
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm('''
def main() -> int:
    rows: tuple[tuple[str, ...], ...] = (("a",), ("b", "c"))
    for value, in rows:
        return len(value)
    return 0
''', filename="tuple_boundary.py")
    assert str(caught.value) == (
        "JVM variadic tuple unpacking is not implemented "
        "while compiling tuple_boundary.main"
    )


def test_fixed_tuple_conversion_retains_an_explicit_boundary():
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm('''
def size(values: tuple[str, ...]) -> int:
    return len(values)

def main() -> int:
    fixed = ("a", "b")
    return size(fixed)
''', filename="tuple_boundary.py")
    assert str(caught.value) == (
        "JVM call to size has incompatible arguments at line 3 "
        "while compiling tuple_boundary.main"
    )
