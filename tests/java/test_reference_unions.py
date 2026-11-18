import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python

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
