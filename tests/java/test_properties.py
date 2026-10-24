import pytest

from tests.backend_semantics import PROPERTY_GETTER_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


def test_shared_property_getter_contract(tmp_path):
    assert_matches_python(PROPERTY_GETTER_CONTRACT.source, tmp_path)


@pytest.mark.parametrize(("annotation", "expression"), [
    ("bool", "True"), ("int", "42"), ("str", '"ready"'),
    ("int8", "int8(127)"), ("float32", "float32(1.25)"),
])
def test_property_getters_preserve_return_representation(tmp_path, annotation, expression):
    assert_text_matches_python(f'''
from pyjs import int8, float32
class Value:
    @property
    def result(self) -> {annotation}:
        return {expression}
def main() -> str:
    value = Value()
    assert value.result == {expression}
    return "matched"
''', tmp_path)


def test_inherited_getter_dispatch_and_receiver_evaluation(tmp_path):
    assert_text_matches_python('''
class Base:
    @property
    def label(self) -> str:
        return "base"
class Child(Base):
    @property
    def label(self) -> str:
        return "child"
class Inherited(Child):
    pass
def create(events: list[str]) -> Base:
    events.append("create")
    return Inherited()
def main() -> str:
    events: list[str] = []
    result = create(events).label
    return result + ":" + "|".join(events)
''', tmp_path)


def test_property_getter_exception_reaches_caller(tmp_path):
    assert_text_matches_python('''
class Value:
    @property
    def result(self) -> str:
        raise ValueError("unavailable")
def main() -> str:
    try:
        return Value().result
    except ValueError as error:
        return str(error)
''', tmp_path)
