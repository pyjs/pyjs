import re
import subprocess
from pathlib import Path

import pytest

from pyjs.android.api import AndroidAPI
from pyjs.java import read_jvm_class, transpile_jvm
from tests.java.test_jvm import java
from tests.semantics.helpers import run_javascript, run_python

WHITESPACE = [chr(value) for value in range(0x110000) if chr(value).isspace()]
RETAINED = ["\0", "\x08", "\x0e", "\x1b", "\x7f", "\u180e", "\u200b", "\ufeff",
            "😀", "\ud800", "\udfff"]
TRIM_SOURCE = '''
def trim(value: str) -> str:
    return value.strip().rstrip()


def main() -> str:
    return trim("  note  ")
'''


@pytest.mark.parametrize("method", ["strip", "rstrip"])
@pytest.mark.parametrize("family", ["whitespace", "retained", "boundaries"])
def test_trimming_matches_python_and_javascript(tmp_path, method, family):
    if family == "whitespace":
        values = [value for char in WHITESPACE for value in (
            char, char * 3 + "note", "note" + char * 3,
            char + "a" + char + "b" + char,
        )]
    elif family == "retained":
        values = [value for char in RETAINED for value in (
            char, " " + char + "\xa0", char + "note" + char,
        )]
    else:
        whitespace = "".join(WHITESPACE)
        values = ["", "note", whitespace, whitespace + "😀 note 😀" + whitespace,
                  "\xa0" * 1024 + "a b" + "\x85" * 1024]
    checks = "\n".join(
        f"    assert trim({value!r}) == {getattr(value, method)()!r}"
        for value in values
    )
    source = f'''
from pyjs import js


@js
def trim(value: str) -> str:
    return value.{method}()


def main() -> int:
{checks}
    return 0
'''
    expected = run_python(source + "\nmain()")
    assert expected.returncode == 0, expected.stderr
    javascript, _ = run_javascript(source)
    assert javascript == expected
    transpile_jvm(source).write(tmp_path)
    actual = subprocess.run(
        [java(), "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert actual.returncode == 0, actual.stderr
    assert actual.stdout == expected.stdout


def test_trimming_calls_only_legacy_string_methods(tmp_path):
    compilation = transpile_jvm(TRIM_SOURCE)
    compilation.write(tmp_path)
    disassembly = subprocess.run(
        [java(), "-m", "jdk.jdeps/com.sun.tools.javap.Main", "-c", "-p",
         str(tmp_path / "PyjsProgram.class")],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout
    # Ignore application wrappers, but compare the complete external string
    # call set so a newer runtime method cannot silently enter this helper.
    references = set(re.findall(
        r"// Method java/lang/String\.(\w+):(\S+)", disassembly,
    ))
    assert references == {
        ("length", "()I"), ("charAt", "(I)C"), ("indexOf", "(I)I"),
        ("substring", "(II)Ljava/lang/String;"),
    }
    methods = read_jvm_class(compilation.classes["PyjsProgram"]).declared_methods(
        "pyjs_string_strip",
    )
    assert [method.descriptor for method in methods] == [
        "(Ljava/lang/String;Z)Ljava/lang/String;",
    ]


def test_trimming_string_methods_exist_at_android_minimum_sdk():
    platform = Path.home() / "Android/Sdk/platforms/android-35"
    if not (platform / "data/api-versions.xml").is_file():
        pytest.skip("Android API 35 availability metadata is not installed")
    with AndroidAPI(platform, 35) as api:
        string = api.require_class("java/lang/String")
        for name, descriptor in (
            ("length", "()I"), ("charAt", "(I)C"), ("indexOf", "(I)I"),
            ("substring", "(II)Ljava/lang/String;"),
        ):
            method = next(method for method in string.methods
                          if method.name == name and method.descriptor == descriptor)
            # The SDK records inherited CharSequence contracts on the interface.
            owner = "java/lang/CharSequence" if name in {"length", "charAt"} else string
            availability = api.method_availability(owner, method)
            assert availability is not None
            assert availability.available_at(21)


def test_trimming_helper_is_not_emitted_when_unused():
    compilation = transpile_jvm('def main() -> str:\n    return "note"')
    main = read_jvm_class(compilation.classes["PyjsProgram"])
    assert main.declared_methods("pyjs_string_strip") == ()
