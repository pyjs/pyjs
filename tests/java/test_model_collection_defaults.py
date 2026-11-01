import pytest
from pydantic import BaseModel, Field

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.java.models import field_info
from tests.backend_semantics import MODEL_COLLECTION_DEFAULTS_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_collection_defaults_contract(tmp_path):
    assert_matches_python(MODEL_COLLECTION_DEFAULTS_CONTRACT.source, tmp_path)


def test_generated_constructor_marks_only_fresh_collection_defaults():
    class Item(BaseModel):
        names: list[str] = Field(default_factory=list)
        counts: dict[str, int] = {}
        count: int = 1

    info = field_info(Item)
    assert info.defaults == {"names": [], "counts": {}, "count": 1}
    assert info.config == {"fresh_collection_defaults": ("names", "counts")}
    assert info.methods["__init__"] == (
        "    def __init__(self, *, names: list[str] = [], counts: dict[str, int] = {}, count: int = 1):\n"
        "        self.names = names\n"
        "        self.counts = counts\n"
        "        self.count = count\n"
    )


@pytest.mark.parametrize("annotation, default", [
    ("List", "[]"),
    ("List", "Field(default_factory=list)"),
    ("Dict", "{}"),
    ("Dict", "Field(default_factory=dict)"),
    ("List", ""),
    ("Dict", ""),
    ("Annotated[List, Field(description='items')]", "[]"),
    ("List | None", "None"),
    ("dict[str, List]", "{}"),
])
def test_unspecialized_collection_fields_have_located_diagnostics(annotation, default):
    source = f'''from typing import Annotated, Dict, List
from pydantic import BaseModel, Field
class Item(BaseModel):
    values: {annotation}{" = " + default if default else ""}
def main() -> int:
    Item()
    return 0
'''
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(source, filename="model.py")
    diagnostic = caught.value.diagnostic
    assert caught.value.filename == "model.py"
    assert diagnostic.code == "PYJS2001"
    assert caught.value.lineno == 3
    assert diagnostic.message == "JVM client model field 'values' has an unsupported type"


def test_collection_defaults_compile_to_android(tmp_path):
    assert_compiles_to_android_dex(MODEL_COLLECTION_DEFAULTS_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("definition", [
    "values: list[str] = Field(default_factory=list)",
    "values: dict[str, int] = Field(default_factory=dict)",
    "values: list[str] = []",
    "values: dict[str, int] = {}",
])
def test_nonnullable_collection_defaults_do_not_accept_explicit_none(definition, tmp_path):
    source = f'''from pydantic import BaseModel, Field
class Item(BaseModel):
    {definition}
def main() -> str:
    try:
        Item.model_validate_json('{{"values":null}}')
    except ValueError:
        return "rejected"
    return "accepted"
'''
    assert_text_matches_python(source, tmp_path)
    constructor = source[:source.index("def main")] + '''def main() -> int:
    Item(values=None)
    return 0
'''
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(constructor, filename="model.py")
    assert caught.value.diagnostic.code == "PYJS1104"
    assert caught.value.lineno == 5


def test_custom_factory_is_rejected_without_executing_it():
    source = '''from pydantic import BaseModel, Field
def factory() -> list[str]:
    raise RuntimeError("factory executed")
class Item(BaseModel):
    names: list[str] = Field(default_factory=factory)
def main() -> int:
    Item()
    return 0
'''
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(source, filename="model.py")
    assert caught.value.diagnostic.code == "PYJS2001"
    assert caught.value.lineno == 4
    assert caught.value.diagnostic.message == (
        "JVM client model field 'names' supports only list/dict default factories"
    )


def test_field_only_model_keeps_fresh_defaults_when_json_is_unsupported(tmp_path):
    assert_text_matches_python('''from pydantic import BaseModel, Field
class Left(BaseModel):
    name: str
class Right(BaseModel):
    name: str
class Item(BaseModel):
    choice: Left | Right
    values: list[str] = Field(default_factory=list)
def main() -> str:
    first = Item(choice=Left(name="left"))
    second = Item(choice=Left(name="left"))
    first.values.append("changed")
    return str(len(second.values))
''', tmp_path)


def test_annotated_nullable_collection_factory(tmp_path):
    assert_text_matches_python('''from typing import Annotated
from pydantic import BaseModel, Field
class Item(BaseModel):
    values: Annotated[list[str], Field(description="values")] | None = Field(default_factory=list)
def main() -> str:
    value = Item()
    assert value.values is not None
    explicit = Item(values=None)
    assert explicit.values is None
    restored = Item.model_validate_json('{}')
    assert restored.values is not None
    return "fresh"
''', tmp_path)
