import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import FIXED_TUPLE_ASSIGNMENT_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_unpacked_fixed_width_locals_preserve_arithmetic(tmp_path):
    assert_text_matches_python('''
from pyjs import int8
def main() -> str:
    first, second = (int8(127), int8(1))
    first += second
    left = int8(0)
    for left, (right,) in [(int8(127), (int8(1),))]:
        left += right
    return str(first) + ":" + str(left)
''', tmp_path)


def test_fixed_tuple_assignment_contract(tmp_path):
    assert_matches_python(FIXED_TUPLE_ASSIGNMENT_CONTRACT.source, tmp_path)


def test_fixed_tuple_assignment_android_dex(tmp_path):
    assert_compiles_to_android_dex(FIXED_TUPLE_ASSIGNMENT_CONTRACT.source, tmp_path)


def test_variadic_assignment_keeps_explicit_boundary():
    with pytest.raises(JVMUnsupported, match="JVM variadic tuple unpacking is not implemented"):
        transpile_jvm('''
def unpack(values: tuple[str, ...]) -> str:
    first, = values
    return first
def main() -> str:
    return unpack(("a",))
''')


def test_list_assignment_keeps_explicit_boundary():
    with pytest.raises(JVMUnsupported, match="JVM can only unpack tuple items"):
        transpile_jvm('''
def main() -> int:
    first, second = [1, 2]
    return first + second
''')


def test_starred_assignment_keeps_explicit_boundary():
    with pytest.raises(JVMUnsupported, match="JVM starred unpacking is not implemented"):
        transpile_jvm('''
def main() -> int:
    first, *rest = (1, 2, 3)
    return first
''')
