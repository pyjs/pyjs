import pytest

from tests.semantics.helpers import assert_semantics


def test_invalid_json_and_schema_errors_are_value_errors():
    assert_semantics('''from pydantic import BaseModel
from pyjs import js
@js
class Item(BaseModel):
    name: str
    count: int = 0
@js
def main() -> None:
    for source in ['{', 'null', '[]', '{}', '{"name":1}',
                   '{"name":"ok","count":1.5}', '{"name":"ok"} trailing']:
        try:
            Item.model_validate_json(source)
        except ValueError:
            print("rejected")
        else:
            print("accepted")
main()
''')


@pytest.mark.parametrize("shape,value", [
    ("{model}", "child"),
    ("list[{model}]", "[child]"),
    ("dict[str, {model}]", "{'key': child}"),
    ("list[list[{model}]]", "[[child]]"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_container_unions_prefer_exact_declared_model_shapes(shape, value, reverse):
    members = [shape.format(model="Parent"), shape.format(model="Child")]
    if reverse:
        members.reverse()
    union = " | ".join(members)
    assert_semantics(f'''from pydantic import BaseModel
from pyjs import js
@js
class Parent(BaseModel):
    name: str
@js
class Child(Parent):
    detail: str
@js
class Packet(BaseModel):
    items: {union}
@js
def main() -> None:
    child = Child(name="nested", detail="preserved")
    packet = Packet(items={value})
    assert 'detail' in packet.model_dump_json()
    assert 'detail' in str(packet.model_dump())
    restored = Packet.model_validate_json(packet.model_dump_json())
    assert 'detail' in restored.model_dump_json()
    print("preserved")
main()
''')


def test_json_float_dictionary_keys_round_trip():
    assert_semantics('''from pydantic import BaseModel
from pyjs import js
@js
class Packet(BaseModel):
    items: dict[float, str]
@js
def main() -> None:
    original = Packet(items={1.5: "one", -2.5: "two"})
    restored = Packet.model_validate_json(original.model_dump_json())
    assert restored.items[1.5] == "one" and restored.items[-2.5] == "two"
    print("preserved")
main()
''')


def test_json_boolean_dictionary_keys_round_trip():
    assert_semantics('''from pydantic import BaseModel
from pyjs import js
@js
class Packet(BaseModel):
    items: dict[bool, str]
@js
def main() -> None:
    original = Packet(items={True: "yes", False: "no"})
    restored = Packet.model_validate_json(original.model_dump_json())
    assert restored.items[True] == "yes" and restored.items[False] == "no"
    print("preserved")
main()
''')


@pytest.mark.parametrize("reverse", [False, True])
def test_json_union_selection_counts_nested_supplied_fields_not_defaults(reverse):
    union = "Detailed | Plain" if reverse else "Plain | Detailed"
    assert_semantics(f'''from pydantic import BaseModel
from pyjs import js
@js
class Entry(BaseModel):
    name: str
@js
class More(Entry):
    detail: str = "default"
@js
class Plain(BaseModel):
    item: Entry
@js
class Detailed(BaseModel):
    item: More
@js
class Packet(BaseModel):
    content: {union}
@js
def main() -> None:
    value = Packet.model_validate_json('{{"content":{{"item":{{"name":"x","detail":"kept"}}}}}}')
    assert 'kept' in value.model_dump_json()
    # Equal supplied-field counts retain declaration order, not most defaults.
    tie = Packet.model_validate_json('{{"content":{{"item":{{"name":"x"}}}}}}')
    print('default' in tie.model_dump_json())
main()
''')


def test_json_dictionary_fields_reject_arrays_including_empty_arrays():
    assert_semantics('''from pydantic import BaseModel
from pyjs import js
@js
class Packet(BaseModel):
    items: dict[str, int]
@js
def main() -> None:
    for source in ['{"items":[]}', '{"items":[1,2]}']:
        try:
            Packet.model_validate_json(source)
        except ValueError:
            print("rejected")
        else:
            print("accepted")
main()
''')
