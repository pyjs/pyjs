import ast
import subprocess

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.java.transpiler import JVMUnsupported
from tests.java.test_jvm import java
from tests.semantics.helpers import run_javascript, run_python


@pytest.mark.parametrize(
    "index", [-9223372036854775808, -8, -1, 0, 2, 4, 9223372036854775807]
)
@pytest.mark.parametrize("values, item", [
    ("[1, 2, 3, 4]", "9"),
    ("[1.25, -2.5, 3.75, 4.0]", "9.125"),
    ('["a", "b", "c", "d"]', '"z"'),
    ("[True, False]", "True"),
])
def test_insert_matches_python_at_boundaries(tmp_path, index, values, item):
    expected_values = ast.literal_eval(values)
    expected_values.insert(index, ast.literal_eval(item))
    checks = "\n".join(
        f"    assert values[{position}] == {value!r}"
        for position, value in enumerate(expected_values)
    )
    source = f'''
def main() -> int:
    values = {values}
    values.insert({index}, {item})
    assert len(values) == {len(expected_values)}
{checks}
    return 0
'''
    expected = run_python(source + "\nmain()")
    assert expected.returncode == 0, expected.stderr
    if abs(index) <= 2**53 - 1:
        javascript, _ = run_javascript(source)
        assert javascript == expected
    transpile_jvm(source).write(tmp_path)
    actual = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, check=False,
    )
    assert actual.returncode == expected.returncode, actual.stderr
    assert actual.stdout == expected.stdout


def test_lower_is_unicode_and_independent_of_default_locale(tmp_path):
    values = ["", "TITLE", "CAFÉ", "İ", "ΟΣ", "😀 DESERET 𐐀"]
    checks = "\n".join(
        f"    assert lower({value!r}) == {value.lower()!r}"
        for value in values
    )
    source = f'''
from pyjs import js


@js
def lower(value: str) -> str:
    return value.lower()


def main() -> int:
{checks}
    return 0
'''
    expected = run_python(source + "\nmain()")
    javascript, _ = run_javascript(source)
    assert javascript == expected
    transpile_jvm(source).write(tmp_path)
    actual = subprocess.run(
        [java(), "-Duser.language=tr", "-Duser.country=TR", "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, check=False,
    )
    assert actual.returncode == expected.returncode, actual.stderr
    assert actual.stdout == expected.stdout


def test_insert_into_empty_reference_list_retains_identity(tmp_path):
    source = '''
from pyjs import js


@js
class Item:
    def __init__(self, value: int):
        self.value = value


def main() -> int:
    first = Item(1)
    items: list[Item] = []
    items.insert(-1, first)
    for index in range(8):
        items.insert(0, Item(index + 2))
    assert items[8] is first
    assert items[0].value == 9
    assert len(items) == 9
    return 0
'''
    expected = run_python(source + "\nmain()")
    javascript, _ = run_javascript(source)
    assert expected.returncode == 0, expected.stderr
    assert javascript == expected
    transpile_jvm(source).write(tmp_path)
    actual = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, check=False,
    )
    assert actual.returncode == 0, actual.stderr


@pytest.mark.parametrize("call, message, column, help_text", [
    (
        'values.insert(0, "wrong")',
        "Argument 'value' to list.insert expects int, got str",
        22,
        "Pass a value compatible with int.",
    ),
    (
        "values.insert(index=0, value=1)",
        "insert() parameter 'index' is positional-only",
        19,
        "Pass 'index' as a positional argument.",
    ),
])
def test_insert_rejects_invalid_argument_types_and_keywords(call, message, column, help_text):
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(f"def main() -> int:\n    values = [1]\n    {call}\n    return 0")
    error = caught.value
    assert error.diagnostic.code == "PYJS1104"
    assert error.diagnostic.message == message
    assert (error.lineno, error.offset) == (3, column)
    assert error.diagnostic.help == (help_text,)


def test_insert_non_integer_index_has_an_explicit_backend_boundary():
    # The shared model accepts index-protocol objects for LLVM. JVM still
    # supports scalar indices only; reject before producing invalid bytecode.
    with pytest.raises(JVMUnsupported, match="unsupported JVM scalar operation insert at line 3"):
        transpile_jvm('def main() -> int:\n    values = [1]\n    values.insert("wrong", 1)\n    return 0')
