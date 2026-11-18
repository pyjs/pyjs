import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python, run_jvm

TEXT_HELPERS = '''
from typing import cast
from pyjs import jvm
from pyjs.android import CharSequence, JavaCharSequence

@jvm.native("java/lang/StringBuilder")
class Builder(JavaCharSequence):
    def __init__(self, text: str) -> None:
        self.value = text

def relay(text: CharSequence) -> CharSequence:
    return text

def text_value(text: CharSequence) -> str:
    if isinstance(text, JavaCharSequence):
        return text.to_string()
    return cast(str, text)

class Holder:
    def __init__(self, text: CharSequence):
        self.text = text

    def read(self) -> CharSequence:
        return self.text
'''


@pytest.mark.parametrize("body", [
    'return text_value(relay("plain 😀"))',
    'return text_value(relay(Builder("native 😀")))',
    '''holder = Holder(relay("before"))
    holder.text = relay(Builder("after"))
    return text_value(holder.read())''',
    '''values: list[CharSequence] = [relay("plain"), relay(Builder("native"))]
    return text_value(values[0]) + ":" + text_value(values[1])''',
], ids=["string-call-return", "native-call-return", "field", "list-items"])
def test_text_reference_union_preserves_runtime_values(tmp_path, body):
    assert_text_matches_python(TEXT_HELPERS + "\ndef main() -> str:\n    " + body + "\n", tmp_path)


@pytest.mark.parametrize("present", [False, True])
def test_optional_text_union_keeps_none_and_concrete_values(tmp_path, present):
    source = TEXT_HELPERS + f'''
def optional(present: bool) -> CharSequence | None:
    if present:
        return relay(Builder("available"))
    return None

def main() -> str:
    text = optional({present})
    return "absent" if text is None else text_value(text)
'''
    assert_text_matches_python(source, tmp_path)


def test_text_union_still_rejects_non_text_arguments():
    with pytest.raises(CompilationError) as caught:
        transpile_jvm('''from pyjs.android import CharSequence
def relay(text: CharSequence) -> CharSequence:
    return text
def main() -> int:
    relay(42)
    return 0
''', filename="text_union.py")
    assert caught.value.filename == "text_union.py"
    assert caught.value.lineno == 5
    assert caught.value.diagnostic.code == "PYJS1104"
    assert caught.value.diagnostic.message == (
        "Argument 'text' to relay expects str|JavaCharSequence, got int"
    )
    assert caught.value.diagnostic.help == (
        "Pass a value compatible with str|JavaCharSequence.",
    )


@pytest.mark.parametrize("present", [False, True])
def test_application_object_optional_assignment_preserves_nominal_values(tmp_path, present):
    assert_matches_python(f'''
class object:
    def __init__(self, rank: int):
        self.rank = rank

def initialize(value: object | None) -> int:
    if value is None:
        value = object(3)
    return value.rank

def main() -> int:
    return initialize(object(7) if {present} else None)
''', tmp_path)


@pytest.mark.parametrize("first", [False, True])
def test_unrelated_reference_union_can_be_stored_and_narrowed(tmp_path, first):
    assert_matches_python(f'''
class First:
    def read(self) -> int:
        return 3

class Second:
    def read(self) -> int:
        return 7

def choose(first: bool) -> First | Second:
    return First() if first else Second()

def main() -> int:
    value = choose({first})
    if isinstance(value, First):
        return value.read()
    return value.read()
''', tmp_path)


@pytest.mark.parametrize("result", [
    "text", "text.upper()", 'text + "!"', '"!" + text',
    'str(text == "abc")', "str(len(text))", "string_argument(text)",
    'text.replace("a", "z")', 'text[1:]', '"b" if text else "e"',
    'f"({text})"', 'str("abc".find(text))', 'str(text in "abc")',
])
def test_negative_text_union_guard_supplies_string_consumers(tmp_path, result):
    source = TEXT_HELPERS.replace("def text_value(text: CharSequence)", "def text_value(text: str | Builder)")
    source = source.replace("isinstance(text, JavaCharSequence)", "isinstance(text, Builder)")
    source = source.replace("return cast(str, text)", f"return {result}")
    source += '''
def string_argument(text: str) -> str:
    return text + "?"

def main() -> str:
    return text_value("abc") + ":" + text_value(Builder("native"))
'''
    assert_text_matches_python(source, tmp_path)


@pytest.mark.parametrize("storage", ["local", "field", "model", "list"])
def test_negative_managed_union_guard_supplies_string_consumers(tmp_path, storage):
    setup = {
        "local": "text = choose(True)",
        "field": "holder = Holder(choose(True))\n    text = holder.text",
        "model": "holder = Model(text=choose(True))\n    text = holder.text",
        "list": "values: list[str | Inner] = [choose(True)]\n    text = values[0]",
    }[storage]
    assert_text_matches_python(f'''
from pydantic import BaseModel

class Inner(BaseModel):
    label: str = "inner"

class Holder:
    def __init__(self, text: str | Inner):
        self.text = text

class Model(BaseModel):
    text: str | Inner

def choose(plain: bool) -> str | Inner:
    return "abc" if plain else Inner()

def main() -> str:
    {setup}
    if isinstance(text, Inner):
        return text.label
    return text.upper()
''', tmp_path)


def test_native_text_interface_guard_keeps_java_string_membership(tmp_path):
    source = TEXT_HELPERS.replace("return cast(str, text)", "return text.upper()")
    source += '''
def main() -> str:
    return text_value("abc") + ":" + text_value(Builder("native"))
'''
    # Native isinstance follows the JVM interface, which String implements.
    # The unreachable Python-string branch must still produce valid bytecode.
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "abc:native"


@pytest.mark.parametrize("expression", [
    "value", "relay(value)", "relay(text=value)", "native_relay(value)",
    "str(isinstance(value, Item))", "str(value is holder.text)",
])
def test_replaced_text_field_keeps_wider_consumers_uncast(tmp_path, expression):
    assert_text_matches_python(f'''
from pyjs import jvm

class Item:
    def __init__(self):
        self.label = "new"

class Holder:
    def __init__(self):
        self.text: str | Item = "old"

    def replace(self) -> None:
        self.text = Item()

def relay(text: str | Item) -> str | Item:
    return text

@jvm.native("java/util/Objects", name="requireNonNull")
def native_relay(text: str | Item) -> str | Item:
    return text

def read(holder: Holder) -> str | Item:
    value = relay("before")
    if not isinstance(holder.text, Item):
        holder.replace()
        value = holder.text
        return {expression}
    return "unexpected"

def main() -> str:
    result = read(Holder())
    if isinstance(result, Item):
        return result.label
    return result
''', tmp_path)
