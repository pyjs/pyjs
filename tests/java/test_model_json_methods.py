"""Application-owned typed JSON uses the same schemas as API transport."""
import json

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex

SOURCE = '''from tests.java.json_models import Page
def main() -> str:
    page = Page.model_validate_json('{"items":[{"name":"hello"}],"scores":{"ok":1.5}}')
    assert page.items[0].name == "hello"
    assert page.items[0].count == 0
    assert page.cursor is None
    restored = Page.model_validate_json(page.model_dump_json())
    assert restored.items[0].name == "hello"
    assert restored.scores["ok"] == 1.5
    return restored.mode
'''


def test_json_methods_round_trip_models(tmp_path):
    assert_text_matches_python(SOURCE, tmp_path)


def test_json_methods_compile_to_android(tmp_path):
    assert_compiles_to_android_dex(SOURCE, tmp_path)


def test_json_subclasses_unicode_and_nested_declared_fields(tmp_path):
    source = '''from tests.java.json_models import Item, ChildItem, Page
def main() -> str:
    child = ChildItem.model_validate_json('{"name":"snow 雪😀"}')
    assert child.count == 5
    assert child.detail == "child"
    restored = ChildItem.model_validate_json(child.model_dump_json())
    assert restored.name == child.name
    page = Page(items=[child], scores={})
    # The declared Item view must not serialize ChildItem-only fields.
    value = Item.model_validate_json(Page.model_validate_json(page.model_dump_json()).items[0].model_dump_json())
    assert value.count == 5
    return value.name
'''
    assert_text_matches_python(source, tmp_path)


@pytest.mark.parametrize("document", ["null", "[]", "{}", '{"name":42}',
                                      '{"name":"ok","extra":1}', '{"name":"ok"}junk'])
def test_invalid_json_has_a_catchable_error(tmp_path, document):
    source = f'''from tests.java.json_models import Item
def main() -> str:
    try:
        Item.model_validate_json({document!r})
    except ValueError:
        return "rejected"
    return "accepted"
'''
    assert_text_matches_python(source, tmp_path)


def test_int64_content_is_not_lost_through_json(tmp_path):
    document = json.dumps({"name": "wide", "count": 9007199254740993})
    source = f'''from tests.java.json_models import Item
def main() -> str:
    original = Item.model_validate_json({document!r})
    restored = Item.model_validate_json(original.model_dump_json())
    return str(restored.count)
'''
    assert_text_matches_python(source, tmp_path)


def test_unsupported_codec_does_not_break_plain_model_construction():
    source = '''from pydantic import BaseModel
class Left(BaseModel):
    name: str
class Right(BaseModel):
    title: str
class Choice(BaseModel):
    item: Left | Right
def main() -> str:
    value = Choice(item=Left(name="left"))
    return "constructed"
'''
    transpile_jvm(source)
    with pytest.raises(CompilationError, match="model operations"):
        transpile_jvm(source.replace('return "constructed"', 'return value.model_dump_json()'))


def test_custom_codec_is_not_silently_replaced():
    source = '''from pydantic import BaseModel
class Item(BaseModel):
    name: str
    def model_dump_json(self) -> str:
        return '"custom"'
def main() -> str:
    return Item(name="value").model_dump_json()
'''
    with pytest.raises(CompilationError, match="model operations"):
        transpile_jvm(source)


@pytest.mark.parametrize("definition,constructor", [
    ("choice: Left | Right", "Child(name='child', choice=Left(name='nested'))"),
    ("def model_dump_json(self) -> str:\n        return 'custom'", "Child(name='child')"),
    ("@classmethod\n    def model_validate_json(cls, text: str):\n        return cls(name='custom')", "Child(name='child')"),
])
@pytest.mark.parametrize("operation", ["dump", "decode", "parent_view"])
def test_unsupported_child_codec_cannot_fall_through_to_parent(definition, constructor, operation):
    source = f'''from pydantic import BaseModel
class Left(BaseModel):
    name: str
class Right(BaseModel):
    title: str
class Parent(BaseModel):
    name: str
class Child(Parent):
    {definition}
def dump_parent(value: Parent) -> str:
    return value.model_dump_json()
def main() -> str:
    value = {constructor}
    return value.name
'''
    transpile_jvm(source)  # Unsupported codecs do not forbid field-only use.
    call = {"dump": "value.model_dump_json()",
            "decode": "Child.model_validate_json('{}').name",
            "parent_view": "dump_parent(value)"}[operation]
    with pytest.raises(CompilationError, match="model operations"):
        transpile_jvm(source.replace("return value.name", "return " + call))


def test_shadowing_codec_diagnostic_is_located():
    source = '''from pydantic import BaseModel
class Parent(BaseModel):
    name: str
class Child(Parent):
    def model_dump_json(self) -> str:
        return 'custom'
def main() -> str:
    return Child(name='x').model_dump_json()
'''
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(source)
    assert str(caught.value) == (
        "JVM client models support typed construction and fields, not model operations "
        "[PYJS2001] (_pyjs_java_.py, line 5)"
    )


@pytest.mark.parametrize("definition", [
    '''class First(BaseModel):
    name: str
    child: 'First | None' = None
class Second(First):
    pass
''',
    '''class First(BaseModel):
    name: str
    def model_dump_json(self) -> str:
        return "custom"
class Second(First):
    pass
''',
    '''class First(BaseModel):
    name: str
    def model_dump_json(self) -> str:
        return "custom"
class Second(BaseModel):
    name: str
    def model_dump_json(self) -> str:
        return "other"
''',
    '''class Left(BaseModel):
    value: str
class Right(BaseModel):
    label: str
class First(BaseModel):
    name: str
    choice: Left | Right | None = None
class Second(BaseModel):
    name: str
    choice: Left | Right | None = None
''',
])
def test_multiple_field_only_models_remain_constructible(tmp_path, definition):
    source = f'''from pydantic import BaseModel
{definition}
def main() -> str:
    first = First(name="one")
    second = Second(name="two")
    return first.name + second.name
'''
    assert_text_matches_python(source, tmp_path)
    for call in ("first.model_dump_json()", "Second.model_validate_json('{}').name"):
        with pytest.raises(CompilationError, match="model operations"):
            transpile_jvm(source.replace("first.name + second.name", call))
