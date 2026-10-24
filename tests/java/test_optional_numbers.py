import pytest

from pyjs.java import JVMUnsupported, read_jvm_class, transpile_jvm
from tests.backend_semantics import OPTIONAL_FLOAT_CONTRACT, OPTIONAL_INTEGER_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_optional_integer_contract(tmp_path):
    assert_matches_python(OPTIONAL_INTEGER_CONTRACT.source, tmp_path)


def test_shared_optional_float_contract(tmp_path):
    assert_matches_python(OPTIONAL_FLOAT_CONTRACT.source, tmp_path)


def test_optional_integer_contract_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(OPTIONAL_INTEGER_CONTRACT.source, tmp_path)


def test_optional_number_signatures_use_boxed_storage_without_changing_scalar_abi():
    compilation = transpile_jvm('''
def integer(value: int | None) -> int | None: return value
def floating(value: float | None) -> float | None: return value
def ordinary(value: int, number: float) -> int: return value
def main() -> int:
    assert integer(None) is None
    assert floating(None) is None
    return ordinary(1, 2.0)
''')
    owner = read_jvm_class(compilation.classes["PyjsProgram"])
    assert owner.declared_methods("integer")[0].descriptor == "(Ljava/lang/Long;)Ljava/lang/Long;"
    assert owner.declared_methods("floating")[0].descriptor == "(Ljava/lang/Double;)Ljava/lang/Double;"
    assert owner.declared_methods("ordinary")[0].descriptor == "(JD)J"


@pytest.mark.parametrize(("annotation", "value", "zero"), [
    ("int", "9007199254740993", "0"),
    ("float", "1.25", "-0.0"),
    ("int8", "int8(127)", "int8(0)"),
    ("float32", "float32(1.25)", "float32(-0.0)"),
])
def test_optional_numeric_truth_equality_and_reassignment(tmp_path, annotation, value, zero):
    assert_text_matches_python(f'''from pyjs import int8, float32
def truth(value: {annotation} | None) -> bool:
    if value:
        return True
    return False
def replace(value: {annotation} | None) -> {annotation} | None:
    if value is None:
        value = {value}
    else:
        value = None
    return value
def main() -> str:
    assert not truth(None) and not truth({zero}) and truth({value})
    assert replace(None) == {value}
    assert replace({value}) is None
    assert replace(None) != None
    assert None != replace(None)
    assert replace({value}) == None
    return "matched"
''', tmp_path)


def test_nullable_float_nan_truth_and_numeric_equality_remain_pythonic(tmp_path):
    assert_text_matches_python('''from pyjs.java import parse_double
def truth(value: float | None) -> bool:
    return bool(value)
def equal(left: float | None, right: float | None) -> bool:
    return left == right
def compare(left: int | None, right: float | None) -> bool:
    return left == right
def main() -> str:
    nan = parse_double("NaN")
    assert truth(nan) and not truth(None)
    assert not equal(nan, nan) and not equal(nan, None)
    assert equal(-0.0, 0.0)
    assert not compare(9007199254740993, 9007199254740992.0)
    assert compare(9007199254740992, 9007199254740992.0)
    assert not compare(0, None) and not compare(None, 0.0)
    assert compare(None, None)
    return "matched"
''', tmp_path)


def test_optional_numbers_in_model_fields_and_collections(tmp_path):
    assert_text_matches_python('''from pydantic import BaseModel
class Page(BaseModel):
    cursor: int | None = None
    score: float | None = None
def number(value: int | None) -> int:
    if value is None:
        return -1
    return value + 1
def score(value: float | None) -> float:
    if value is None:
        return -1.0
    return value + 0.5
def main() -> str:
    page = Page()
    assert page.cursor is None and page.score is None
    page.cursor = 9007199254740993
    page.score = 1.25
    assert number(page.cursor) == 9007199254740994
    assert score(page.score) == 1.75
    values: list[int | None] = [None, 1, 9007199254740993]
    assert number(values[0]) == -1
    assert values[2] == 9007199254740993
    values.append(None)
    assert values[-1] is None
    result: dict[str, float | None] = {"missing": None, "found": 2.5}
    assert score(result["missing"]) == -1.0
    assert score(result["found"]) == 3.0
    return "matched"
''', tmp_path)


@pytest.mark.parametrize(("annotation", "value"), [("int", "9007199254740993"), ("float", "1.25")])
def test_optional_numeric_collections_and_variadic_tuple_storage(tmp_path, annotation, value):
    assert_text_matches_python(f'''
def pair(value: {annotation} | None) -> tuple[{annotation} | None, ...]:
    return None, value
def main() -> str:
    values: list[{annotation} | None] = [None]
    values.append({value})
    values.insert(0, {value})
    values[1] = {value}
    copied = list(values)
    values[0] = None
    assert copied[0] == {value} and values[0] is None
    assert len(copied) == 3 and copied[-1] == {value}
    items = pair({value})
    assert items[0] is None and items[1] == {value}
    mapping: dict[str, {annotation} | None] = {{"present": {value}, "empty": None}}
    assert mapping.get("missing") is None
    assert mapping.get("empty", {value}) is None
    assert mapping.get("present") == {value}
    mapping["present"] = None
    assert mapping["present"] is None
    return "matched"
''', tmp_path)


def test_mixed_numeric_union_storage_retains_a_focused_boundary():
    with pytest.raises(JVMUnsupported, match="JVM union has incompatible runtime types"):
        transpile_jvm('''
def accept(value: int | float | None) -> int:
    return 0 if value is None else 1
def main() -> int:
    return accept(None) + accept(1) + accept(1.5)
''')


def test_nullable_numeric_factory_is_evaluated_once_for_none_and_truth_tests(tmp_path):
    assert_text_matches_python('''
def value(events: list[int], present: bool) -> int | None:
    events.append(1)
    return 3 if present else None
def main() -> str:
    events: list[int] = []
    assert value(events, True) is not None
    assert value(events, False) is None
    assert bool(value(events, True))
    assert not bool(value(events, False))
    assert not bool() and not bool(None)
    assert len(events) == 4
    return "matched"
''', tmp_path)


@pytest.mark.parametrize("annotation", ["int", "float"])
@pytest.mark.parametrize("operator", ["is", "is not"])
def test_nullable_numeric_identity_is_not_java_wrapper_identity(annotation, operator):
    with pytest.raises(JVMUnsupported, match="numeric identity comparisons are only supported against None"):
        transpile_jvm(f'''
def identical(left: {annotation} | None, right: {annotation} | None) -> bool:
    return left {operator} right
def main() -> bool:
    return identical(None, None)
''')


@pytest.mark.parametrize("annotation", ["int", "float"])
def test_nullable_numeric_keys_do_not_admit_java_hash_semantics(annotation):
    with pytest.raises(JVMUnsupported, match="do not support nullable numeric keys"):
        transpile_jvm(f'''
def main() -> int:
    values: dict[{annotation} | None, int] = {{None: 1}}
    return values[None]
''')


def test_explicit_nullable_integer_cast_preserves_precision(tmp_path):
    assert_text_matches_python('''from typing import cast
def required(value: int | None) -> int:
    return cast(int, value)
def main() -> str:
    assert required(9007199254740993) == 9007199254740993
    return "matched"
''', tmp_path)


def test_numeric_identity_guard_preserves_exception_class_tokens(tmp_path):
    assert_text_matches_python('''
class Scope:
    def __enter__(self) -> None:
        pass
    def __exit__(self, token: object, value: object, traceback: object) -> bool:
        assert token is ValueError
        assert token is not TypeError
        assert token is not None
        return True
def main() -> str:
    with Scope():
        raise ValueError("suppressed")
    return "matched"
''', tmp_path)
