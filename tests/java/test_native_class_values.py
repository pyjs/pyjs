import subprocess

import pytest

from pyjs.java import transpile_jvm
from tests.java.test_jvm import java


@pytest.mark.parametrize("expression, expected", [
    ("StringBuilder", "[Ljava.lang.StringBuilder;"),
    ("TextSequence", "[Ljava.lang.CharSequence;"),
])
def test_native_class_values_use_the_runtime_owner_without_constructing_an_instance(
    tmp_path, expression, expected,
):
    source = f'''
from typing import Annotated
from pyjs import jvm
from pyjs.java import StringBuilder, i32
from pyjs.java.primitives import Reference

@jvm.native("java/lang/CharSequence", interface=True)
class TextSequence:
    pass

@jvm.native("java/lang/Class")
class JavaClass:
    def getName(self) -> str: ...

@jvm.native("java/lang/Object")
class JavaObject:
    def getClass(self) -> JavaClass: ...

@jvm.native("java/lang/reflect/Array", name="newInstance")
def array(value: Annotated[type[object], Reference("java/lang/Class")], size: i32) -> JavaObject: ...

def main() -> str:
    return array({expression}, i32(0)).getClass().getName()
'''
    compilation = transpile_jvm(source)
    compilation.write(tmp_path)
    assert not any(name.endswith(("$StringBuilder", "$TextSequence"))
                   for name in compilation.classes)
    result = subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


def test_separate_bindings_of_one_native_owner_retain_both_declared_interfaces(tmp_path):
    source = '''
from typing import Annotated
from pyjs import jvm
from pyjs.java import i32
from pyjs.java.primitives import Reference

@jvm.native("java/lang/CharSequence", interface=True)
class Sequence:
    def length(self) -> i32: ...

@jvm.native("java/lang/Appendable", interface=True)
class Appendable:
    def append(self, value: Annotated[str, Reference("java/lang/CharSequence")]) -> Appendable: ...

    @jvm.native("java/lang/Object", name="toString", invocation="virtual")
    def to_string(self) -> str: ...

@jvm.native("java/lang/StringBuilder")
class ReadBuilder(Sequence):
    def __init__(self, text: str) -> None: ...

@jvm.native("java/lang/StringBuilder")
class WriteBuilder(Appendable):
    def __init__(self, text: str) -> None: ...

def main() -> str:
    reader = ReadBuilder("abc")
    writer = WriteBuilder("xy")
    return str(reader.length()) + ":" + writer.append("!").to_string()
'''
    compilation = transpile_jvm(source)
    compilation.write(tmp_path)
    result = subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "3:xy!"
