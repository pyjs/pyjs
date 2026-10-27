"""Small standard-library operations used by portable document controllers."""
import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import DOCUMENT_COLLECTION_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


def test_shared_document_collection_contract(tmp_path):
    assert_matches_python(DOCUMENT_COLLECTION_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("annotation, values, needle", [
    ("str", '["a", "雪", "a"]', '"a"'),
    ("int", '[9007199254740993, 2, 9007199254740993]', "9007199254740993"),
    ("bool", '[True, False, True]', "True"),
])
def test_remove_first_match_preserves_aliases_and_missing_raises(tmp_path, annotation, values, needle):
    assert_text_matches_python(f'''def main() -> str:
    values: list[{annotation}] = {values}
    alias = values
    values.remove({needle})
    assert len(alias) == 2
    assert alias[1] == {needle}
    values.remove({needle})
    assert len(alias) == 1
    try:
        values.remove({needle})
    except ValueError as error:
        assert str(error) == "list.remove(x): x not in list"
        assert len(values) == 1
    else:
        raise AssertionError("missing item must raise")
    values.remove(values[0])
    assert len(alias) == 0
    values.append({needle})
    assert alias[0] == {needle}
    return "ok"
''', tmp_path)


def test_list_unpack_evaluation_order_and_storage_independence(tmp_path):
    assert_text_matches_python('''def items(events: list[str], name: str) -> list[str]:
    events.append(name)
    return [name, name]
def item(events: list[str]) -> str:
    events.append("middle")
    return "middle"
def main() -> str:
    events: list[str] = []
    values = [*items(events, "first"), item(events), *items(events, "last")]
    copied = [*values]
    values[0] = "changed"
    assert copied[0] == "first"
    assert len(values) == 5
    assert ",".join(events) == "first,middle,last"
    empty: list[str] = []
    assert len([*empty]) == 0
    numbers = [1, 2]
    doubles = [1.25, 2.5]
    assert [0, *numbers, 3][2] == 2
    assert [*doubles, 3.5][1] == 2.5
    return ",".join(copied)
''', tmp_path)


def test_set_iterable_construction_deduplicates_and_copies(tmp_path):
    assert_text_matches_python('''def main() -> str:
    values = ["雪", "a", "雪"]
    unique = set(values)
    assert len(unique) == 2
    assert "雪" in unique
    copy = set(unique)
    unique.clear()
    assert "雪" in copy
    assert len(set("雪a雪")) == 2
    mapping = {"a": "value", "b": "another"}
    keys = set(mapping.keys())
    assert "a" in keys and "value" not in keys
    empty: list[str] = []
    assert len(set(empty)) == 0
    return ",".join(sorted(copy))
''', tmp_path)


def test_setdefault_stores_and_returns_the_same_default_with_eager_evaluation(tmp_path):
    assert_text_matches_python('''def default(events: list[str]) -> list[str]:
    events.append("default")
    return []
def main() -> str:
    events: list[str] = []
    mapping: dict[str, list[str]] = {}
    mapping.setdefault("a", default(events)).append("first")
    mapping.setdefault("a", default(events)).append("second")
    assert len(events) == 2
    assert len(mapping["a"]) == 2
    numbers: dict[str, int] = {}
    assert numbers.setdefault("x", 12) == 12
    assert numbers.setdefault("x", 99) == 12
    return ",".join(mapping["a"])
''', tmp_path)


def test_math_isfinite_import_forms_and_integer_conversion(tmp_path):
    assert_text_matches_python('''import math
from math import isfinite as finite
def main() -> str:
    assert finite(1.0) and math.isfinite(-0.0)
    assert finite(9223372036854775807)
    assert not finite(1e309) and not finite(-1e309)
    assert not finite(1e309 - 1e309)
    return "ok"
''', tmp_path)


@pytest.mark.parametrize("initializer", [" = None", ""])
def test_native_reference_class_fields_use_declared_type_not_placeholder(tmp_path, initializer):
    source = '''from typing import Annotated, ClassVar
from pyjs import jvm
@jvm.native("java/util/concurrent/TimeUnit")
class TimeUnit:
    DAYS: ClassVar[Annotated[TimeUnit, jvm.field(writable=False)]]INITIALIZER
    def toMillis(self, duration: int) -> int: ...
def main() -> str:
    return str(TimeUnit.DAYS.toMillis(1))
'''.replace("INITIALIZER", initializer)
    from tests.java.test_exceptions import run_jvm

    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "86400000"


@pytest.mark.parametrize("body, message", [
    ('values = [1.0]\n    values.remove(1.0)', "JVM list remove\\(\\) requires matching"),
    ('values = [*(1, 2)]', "JVM list unpacking requires a list"),
    ('values: dict[str, str] = {}\n    values.setdefault("a")', "requires an explicit default"),
    ('values = set([1, 2])', "JVM sets currently require reference items"),
    ('values = ["a"]\n    values.remove(value="a")', "requires one positional argument"),
])
def test_new_collection_support_keeps_explicit_boundaries(body, message):
    with pytest.raises(JVMUnsupported, match=message):
        transpile_jvm(f"def main() -> int:\n    {body}\n    return 0\n")


def test_setdefault_keyword_default_retains_positional_only_diagnostic():
    with pytest.raises(CompilationError, match="parameter 'default' is positional-only") as caught:
        transpile_jvm('def main() -> int:\n    values: dict[str, str] = {}\n'
                      '    values.setdefault("a", default="b")\n    return 0\n', filename="lookup.py")
    assert caught.value.lineno == 3
    assert caught.value.diagnostic.code == "PYJS1104"


def test_java_only_callback_inherited_through_a_native_base_is_retained(tmp_path):
    from tests.java.test_exceptions import run_jvm

    source = '''from pyjs import jvm
@jvm.native("java/lang/Object")
class NativeObject:
    def toString(self) -> str: ...
@jvm.native("java/util/ArrayList")
class NativeList(NativeObject):
    def __init__(self) -> None: ...
@jvm.native("java/util/Objects", name="toString")
def describe(value: NativeObject) -> str: ...
class CustomList(NativeList):
    def __init__(self):
        super().__init__()
    def toString(self) -> str:
        return "inherited native callback"
def main() -> str:
    return describe(CustomList())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "inherited native callback"
