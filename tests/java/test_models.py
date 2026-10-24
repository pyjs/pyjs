import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex

MODEL_CONSTRUCTION = '''
from pydantic import BaseModel
from typing import Literal
class Item(BaseModel):
    title: str
    count: int = 1
class Entry(Item):
    kind: Literal["text", "list"] = "text"
    enabled: bool = True
    comment: str | None = None
class Page(BaseModel):
    items: list[Entry]
def main() -> str:
    entry = Entry(title="hello")
    assert entry.count == 1 and entry.enabled and entry.comment is None
    page = Page(items=[entry, Entry(title="second", count=2, kind="list")])
    page.items[0].title = "changed"
    assert page.items[1].kind == "list"
    assert page.items[1].count == 2
    return page.items[0].title
'''


def test_typed_model_construction_defaults_inheritance_and_nested_fields(tmp_path):
    assert_text_matches_python(MODEL_CONSTRUCTION, tmp_path)


def test_model_construction_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(MODEL_CONSTRUCTION, tmp_path)


@pytest.mark.parametrize("call", ['Item("bad")', 'Item()', 'Item(title=1)', 'Item(title="ok", extra=1)'])
def test_model_constructor_rejects_invalid_arguments(call):
    with pytest.raises(CompilationError):
        transpile_jvm(f'''from pydantic import BaseModel
class Item(BaseModel):
    title: str
def main() -> str:
    return {call}.title
''', filename="model.py")


@pytest.mark.parametrize("expression", ['value == Item(title="hello")', 'value != value', 'str(value)', 'repr(value)', 'hash(value)'])
def test_model_operations_do_not_silently_use_object_semantics(expression):
    with pytest.raises(CompilationError, match="JVM client models support typed construction and fields, not model operations"):
        transpile_jvm(f'''from pydantic import BaseModel
class Item(BaseModel):
    title: str
def main() -> int:
    value = Item(title="hello")
    {expression}
    return 0
''', filename="model.py")


def test_model_field_named_self_has_a_focused_boundary():
    with pytest.raises(CompilationError, match="JVM client model fields cannot be named 'self'"):
        transpile_jvm('''from pydantic import BaseModel
class Item(BaseModel):
    self: str
def main() -> str:
    return Item(self="hello").self
''', filename="model.py")


def test_module_qualified_literal_and_aliased_model_base(tmp_path):
    assert_text_matches_python('''import typing
from pydantic import BaseModel as Validated
class Item(Validated):
    kind: typing.Literal["text", "list"] = "text"
def main() -> str:
    return Item().kind
''', tmp_path)


@pytest.mark.parametrize(("field", "message"), [
    ('name: str = Field(alias="title")', "does not support aliases"),
    ('names: list[str] = Field(default_factory=list)', "does not support default factories"),
    ('names: list[str] = []', "requires a scalar default"),
    ('name: str = Field(default="ok", frozen=True)', "does not support freezing or exclusion"),
    ('name: str = Field(default="ok", exclude=True)', "does not support freezing or exclusion"),
    ('name: bytes = b"ok"', "has an unsupported type"),
    ('number: float = float("inf")', "requires a finite default"),
])
def test_unsupported_model_fields_have_located_diagnostics(field, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_jvm(f'''from pydantic import BaseModel, Field
class Item(BaseModel):
    {field}
def main() -> int:
    Item()
    return 0
''', filename="model.py")
    assert caught.value.filename == "model.py"
    assert caught.value.lineno == 2
    assert caught.value.diagnostic.code == "PYJS2001"


def test_host_model_methods_are_not_emitted():
    compilation = transpile_jvm('''from pydantic import BaseModel
class Item(BaseModel):
    title: str
    def server_only(self) -> str:
        raise RuntimeError("host implementation must not ship")
def main() -> str:
    return Item(title="hello").title
''', filename="model.py")
    assert not any(b"host implementation must not ship" in value for value in compilation.classes.values())


@pytest.mark.parametrize(("body", "message"), [
    ('model_config = ConfigDict(frozen=True)', "Unsupported JVM client model configuration: frozen"),
    ('model_config = ConfigDict(extra="allow")', "do not support dynamic extra fields"),
    ('def model_post_init(self, context: object) -> None: pass', "do not support custom initialization"),
    ('def __init__(self): super().__init__()', "do not support custom initialization"),
    ('@field_validator("name")\n    @classmethod\n    def validate_name(cls, value: str) -> str: return value',
     "do not yet support custom validators or serializers"),
    ('@field_serializer("name")\n    def serialize_name(self, value: str) -> str: return value',
     "do not yet support custom validators or serializers"),
])
def test_model_customizations_are_not_silently_ignored(body, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_jvm(f'''from pydantic import BaseModel, ConfigDict, field_validator, field_serializer
class Item(BaseModel):
    name: str = "hello"
    {body}
def main() -> str:
    return Item().name
''', filename="model.py")
    assert caught.value.filename == "model.py"
    assert caught.value.lineno == 2
    assert caught.value.diagnostic.code == "PYJS2001"


def test_model_library_keeps_its_pydantic_version_gate(monkeypatch):
    from pydantic import BaseModel

    from pyjs.analysis import libraries
    from pyjs.java.models import LIBRARY

    monkeypatch.setattr(libraries.metadata, "version", lambda _: "3.0.0")
    with pytest.raises(libraries.LibraryCompatibilityError, match="supports pydantic >=2.0,<3.0"):
        LIBRARY.replacement(BaseModel)
