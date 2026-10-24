import subprocess
from textwrap import dedent

from pyjs.java import transpile_jvm
from pyjs.java.classfile import ClassFile, Method
from tests.java.test_jvm import java
from tests.semantics.helpers import run_python


def assert_small_stack_matches_python(source, directory):
    source = dedent(source)
    expected = run_python(source + "\nprint(main())\n")
    assert expected.returncode == 0, expected.stderr
    transpile_jvm(source).write(directory)
    actual = subprocess.run(
        [java(), "-Xss256k", "-Xcomp", "-Xmx64m", "-Xverify:all", "-cp", str(directory), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )
    assert actual.stderr == "", actual.stderr
    assert actual.returncode == int(expected.stdout.strip())


def test_jit_calls_do_not_reserve_the_maximum_jvm_operand_stack(tmp_path):
    assert_small_stack_matches_python('''
        def descend(depth: int) -> int:
            if depth == 0:
                return 42
            return descend(depth - 1)
        def main() -> int:
            return descend(50)
    ''', tmp_path)


def test_exception_handlers_and_wide_operands_verify_with_bounded_stack(tmp_path):
    assert_small_stack_matches_python('''
        def descend(depth: int) -> int:
            try:
                if depth == 0:
                    raise ValueError("bottom")
                return descend(depth - 1) + 1
            except ValueError:
                return 1
            finally:
                depth += 1
        def main() -> int:
            return descend(30)
    ''', tmp_path)


def test_class_writer_caps_large_stack_requests_but_retains_tighter_bounds():
    owner = ClassFile("StackBound")
    for requested, expected in ((65535, 5), (2, 2)):
        method = Method(0x0009, "value", "()J", bytes([0x09, 0xAD]), requested, 0)
        encoded = owner.render_method(method)
        # method_info header, Code attribute header, then max_stack (JVMS 4.7.3).
        assert int.from_bytes(encoded[14:16]) == expected


