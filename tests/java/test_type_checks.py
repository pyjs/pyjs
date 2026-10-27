import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import ISINSTANCE_LITERAL_TUPLE_CONTRACT
from tests.java.test_exceptions import assert_matches_python


def test_literal_tuple_checks_match_python_with_one_subject_evaluation(tmp_path):
    assert_matches_python(ISINSTANCE_LITERAL_TUPLE_CONTRACT.source, tmp_path)


def test_singleton_tuple_checks_narrow_subclasses(tmp_path):
    assert_matches_python('''
        class Base:
            pass
        class Left(Base):
            def __init__(self):
                self.value = 3
        class Right(Base):
            def __init__(self):
                self.value = 5
        def value(item: Base) -> int:
            if isinstance(item, (Left,)):
                return item.value
            if isinstance(item, (Right,)):
                return item.value
            return 0
        def main() -> int:
            return value(Left()) + value(Right()) + value(Base())
    ''', tmp_path)


def test_tuple_checks_retain_builtin_class_boundary():
    with pytest.raises(JVMUnsupported, match="isinstance requires an emitted or native class"):
        transpile_jvm('''
            def check(value: str | None) -> bool:
                return isinstance(value, (str,))
            def main() -> int:
                return int(check("value"))
        ''')


@pytest.mark.parametrize("value", ["None", "1", "1.25", "True", "'text'"])
def test_empty_tuple_accepts_any_subject(value, tmp_path):
    assert_matches_python(f"def main() -> int:\n    return int(isinstance({value}, ()))\n", tmp_path)


def test_tuple_subject_exception_is_not_skipped(tmp_path):
    assert_matches_python('''
        class Item:
            pass
        def fail() -> Item:
            raise ValueError("subject")
        def main() -> int:
            try:
                isinstance(fail(), ())
            except ValueError:
                return 42
            return 1
    ''', tmp_path)
