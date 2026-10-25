import shutil
import subprocess

import pytest

from tests.java.test_exceptions import run_jvm

SOURCE = '''
from pyjs import jvm
from pyjs.java.collections import JavaList

@jvm.native("java/util/List", name="of", interface=True)
def empty_list() -> JavaList: ...

def main() -> str:
    value = empty_list()
    assert value.size() == 0
    return "empty interface factory"
'''


def test_static_interface_factory_uses_interface_method_reference(tmp_path):
    result = run_jvm(SOURCE, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "empty interface factory"


def test_static_interface_factory_does_not_require_an_owner_class_declaration(tmp_path):
    # No class declaration for the owner is reachable. Its interface-ness must
    # come from the function binding, not an incidental returned/native class.
    javac = shutil.which("javac")
    if javac is None:
        pytest.skip("javac is required")
    java_source = tmp_path / "SampleFactory.java"
    java_source.write_text("public interface SampleFactory { static int value() { return 42; } }")
    subprocess.run([javac, str(java_source)], check=True, capture_output=True, timeout=30)
    source = '''
from pyjs import jvm
from pyjs.java import i32
@jvm.native("SampleFactory", name="value", interface=True)
def value() -> i32: ...
def main() -> str:
    return str(int(value()))
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "42"


def test_interface_bridge_preserves_wide_arguments_results_and_exceptions(tmp_path):
    javac = shutil.which("javac")
    if javac is None:
        pytest.skip("javac is required")
    java_source = tmp_path / "WideFactory.java"
    java_source.write_text('''public interface WideFactory {
        static double add(long a, double b, float c, int d) { return a + b + c + d; }
        static void check(boolean fail) {
            if (fail) throw new IllegalArgumentException("rejected");
        }
    }''')
    subprocess.run([javac, str(java_source)], check=True, capture_output=True, timeout=30)
    result = run_jvm('''
from pyjs import jvm
from pyjs.java import i32, f32
@jvm.native("WideFactory", name="add", interface=True)
def add(a: int, b: float, c: f32, d: i32) -> float: ...
@jvm.native("WideFactory", name="check", interface=True)
def check(fail: bool) -> None: ...
def main() -> str:
    for _ in range(2):
        assert add(10000000000, 0.25, f32(0.5), i32(2)) == 10000000002.75
        check(False)
    try:
        check(True)
    except Exception:
        return "wide ABI and propagated exception"
    return "missing exception"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "wide ABI and propagated exception"
