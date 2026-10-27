import re
import subprocess

import pytest

from pyjs.android.api import AndroidAPI
from pyjs.java import JVMUnsupported, read_jvm_class, transpile_jvm
from tests.backend_semantics import (
    OPTIONAL_BRANCH_CONTRACT,
    OPTIONAL_STRING_CONTRACT,
    STRING_SEARCH_CASES,
    UNION_NONE_GUARD_CONTRACT,
)
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_jvm import java
from tests.java.test_native_boundaries import run_jvm
from tests.semantics.helpers import run_javascript, run_python


def test_optional_string_truth_handles_missing_empty_and_present(tmp_path):
    assert_text_matches_python('''
def check(value: str | None) -> int:
    if value:
        return 1
    return 0
def main() -> str:
    return str(check(None)) + str(check("")) + str(check("yes"))
''', tmp_path)


@pytest.mark.parametrize("method", ["lower", "upper"])
@pytest.mark.parametrize("value", ["", "Ii", "Straße ÉΣΑ 😀"])
def test_case_conversion_is_independent_of_default_locale(tmp_path, method, value):
    source = f"def main() -> str:\n    return {value!r}.{method}()\n"
    expected = run_python(source + "\nprint(main(), end='')\n")
    assert expected.returncode == 0, expected.stderr
    transpile_jvm(source).write(tmp_path)
    result = subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-Duser.language=tr",
         "-Duser.country=TR", "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected.stdout


def test_multiple_concrete_members_reach_jvm_isinstance_boundary():
    # Shared analysis now passes the multi-member None guard. JVM's builtin
    # isinstance lowering remains a separate, explicit unsupported boundary.
    with pytest.raises(JVMUnsupported, match="isinstance requires an emitted or native class.*compiling"):
        transpile_jvm(UNION_NONE_GUARD_CONTRACT.source)


@pytest.mark.parametrize(("expression", "result_type", "helpers"), [
    ("value", "str", []),
    ("len(value)", "int", ["length"]),
    ("value[-1]", "str", ["length", "getitem"]),
    ("value * 2", "str", ["repeat"]),
    ("value.strip().rstrip()", "str", ["strip"]),
    ("int(value)", "int", ["int"]),
    ('int("note" in value)', "int", ["boundary", "contains"]),
    ('int(value.startswith("note"))', "int", ["boundary", "startswith"]),
    ('int(value.endswith("note"))', "int", ["boundary", "endswith"]),
    ("value[-1].strip() * len(value)", "str",
     ["length", "getitem", "repeat", "strip"]),
])
def test_string_helpers_are_emitted_once_with_their_dependencies(
    expression, result_type, helpers,
):
    compilation = transpile_jvm(f'''
def main() -> {result_type}:
    value = "  note 😀 "
    return {expression}
''')
    main = read_jvm_class(compilation.classes["PyjsProgram"])
    assert [method.name for method in main.methods
            if method.name.startswith("pyjs_string_")] == [
        f"pyjs_string_{name}" for name in helpers
    ]


def test_string_indexing_resolves_helpers_in_the_requested_main_class(tmp_path):
    compilation = transpile_jvm('''
def main() -> str:
    return "note 😀"[-1]
''', class_name="Notes")
    compilation.write(tmp_path)
    actual = subprocess.run(
        [java(), "-cp", str(tmp_path), "Notes"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert actual.returncode == 0, actual.stderr
    assert actual.stdout == "😀"


@pytest.mark.parametrize("value", [
    " 42 ", "1_000", "+1_0", "-0", "0007", "\xa0-٤_٢\u2007",
    "𝟜𝟚", "\t+42\n", "9223372036854775807", "-9223372036854775808",
    "0" * 3000 + "1",
])
def test_integer_parsing_matches_python(tmp_path, value):
    source = f"def main() -> str:\n    return str(int({value!r}))\n"
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(int(value))


@pytest.mark.parametrize("value", [
    "", " ", "_1", "1_", "1__2", "+_1", "+ 1", "1 2", "1.0", "0x10",
    "²", "\x1c42", "42\x1f",
])
def test_integer_parsing_rejects_invalid_python_spellings(tmp_path, value):
    with pytest.raises(ValueError):
        int(value)
    result = run_jvm(f"def main() -> int:\n    return int({value!r})\n", tmp_path)
    assert result.returncode != 0
    assert "PyjsProgram$exception$ValueError" in result.stderr


@pytest.mark.parametrize("value", ["9223372036854775808", "-9223372036854775809"])
def test_integer_parsing_rejects_out_of_range_values(tmp_path, value):
    result = run_jvm(f"def main() -> int:\n    return int({value!r})\n", tmp_path)
    assert result.returncode != 0
    assert "PyjsProgram$exception$OverflowError" in result.stderr


@pytest.mark.parametrize(("value", "count"), [
    ("x", 2**32), ("x", 2**31), ("xy", 2**30), ("😀", 2**30), ("x", 2**63 - 1),
])
def test_string_repetition_rejects_oversized_results_before_narrowing(
    tmp_path, value, count,
):
    result = run_jvm(f"def main() -> str:\n    return {value!r} * {count}\n", tmp_path)
    assert result.returncode != 0
    assert "PyjsProgram$exception$MemoryError" in result.stderr
    assert "Java heap space" not in result.stderr


@pytest.mark.parametrize(("value", "count"), [
    ("", 2**63 - 1), ("x", -2**63), ("x", 0), ("😀", 3),
])
def test_string_repetition_preserves_empty_and_small_results(tmp_path, value, count):
    result = run_jvm(f"def main() -> str:\n    return {value!r} * {count}\n", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == value * count


@pytest.mark.parametrize("contract", [OPTIONAL_STRING_CONTRACT, OPTIONAL_BRANCH_CONTRACT], ids=["short_circuit", "branch_merge"])
def test_optional_string_short_circuit_contract_matches_python_and_javascript(tmp_path, contract):
    expected = run_python(contract.source + "\nassert main() == 0\n")
    assert expected.returncode == 0, expected.stderr
    javascript, _ = run_javascript(contract.print_source)
    assert javascript.returncode == 0, javascript.stderr
    assert javascript.stdout.strip() == "0"
    result = run_jvm(contract.source, tmp_path)
    assert result.returncode == 0, contract.failure(result.returncode) + result.stderr


@pytest.mark.parametrize("method", ["contains", "startswith", "endswith"])
def test_string_search_respects_code_point_boundaries(tmp_path, method):
    expression = "needle in value" if method == "contains" else f"value.{method}(needle)"
    checks = "\n".join(
        f"    assert search({value!r}, {needle!r}) == "
        f"{(needle in value) if method == 'contains' else getattr(value, method)(needle)!r}"
        for value, needle in STRING_SEARCH_CASES
    )
    source = f'''
def search(value: str, needle: str) -> bool:
    return {expression}

def main() -> int:
{checks}
    return 0
'''
    expected = run_python(source + "\nassert main() == 0\n")
    assert expected.returncode == 0, expected.stderr
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr


LEGACY_REPEAT_METHODS = {
    ("java/lang/String", "getBytes", "(Ljava/lang/String;)[B"),
    ("java/lang/String", "length", "()I"),
    ("java/lang/StringBuilder", "<init>", "(I)V"),
    ("java/lang/StringBuilder", "append", "(Ljava/lang/String;)Ljava/lang/StringBuilder;"),
    ("java/lang/StringBuilder", "toString", "()Ljava/lang/String;"),
}


def test_repetition_calls_only_android_21_string_methods(tmp_path):
    transpile_jvm('def main() -> str:\n    return "ab" * 3\n').write(tmp_path)
    disassembly = subprocess.run(
        [java(), "-m", "jdk.jdeps/com.sun.tools.javap.Main", "-c", "-p",
         str(tmp_path / "PyjsProgram.class")],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout
    # Check every external string call, including the executable wrapper's
    # UTF-8 conversion, so newer APIs cannot enter unnoticed.
    references = set(re.findall(
        r'// Method (java/lang/String(?:Builder)?)\."?([\w<>]+)"?:(\S+)',
        disassembly,
    ))
    assert references == LEGACY_REPEAT_METHODS
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 availability metadata is not installed")
    with api:
        for owner, name, descriptor in LEGACY_REPEAT_METHODS:
            cls = api.require_class(owner)
            method = next(method for method in cls.methods
                          if method.name == name and method.descriptor == descriptor)
            declared_owner = {
                "length": "java/lang/CharSequence", "toString": "java/lang/Object",
            }.get(name, owner)
            availability = api.method_availability(declared_owner, method)
            assert availability is not None
            assert availability.available_at(21), (owner, name, descriptor)
