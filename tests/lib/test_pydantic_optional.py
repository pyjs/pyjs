import pytest
from pydantic import BaseModel, ConfigDict

from pyjs import js
from pyjs.javascript.source import compile_source
from pyjs.tooling.node import Node


@js
class Child(BaseModel):
    value: int


@js
class OptionalValues(BaseModel):
    count: int | None = None
    text: str | None = None
    child: Child | None = None
    reversed_child: None | Child = None
    items: list[Child] | None = None
    mapping: dict[int | None, str] | None = None


@js
class StrictValues(OptionalValues):
    model_config = ConfigDict(strict=True)


@js
class DetailedChild(Child):
    description: str


@js
class OptionalChoice(BaseModel):
    child: Child | DetailedChild | None = None


@pytest.mark.pyjs_web
@js
def test_optional_values_preserve_defaults_coercion_and_nested_models():
    empty = OptionalValues.model_validate_json('{}')
    assert empty.count is None and empty.text is None and empty.child is None
    assert empty.reversed_child is None and empty.items is None and empty.mapping is None
    value = OptionalValues.model_validate_json(
        '{"count":"7","text":"","child":{"value":1},'
        '"reversed_child":{"value":2},"items":[{"value":3}],"mapping":{"4":"four"}}')
    assert value.count == 7 and value.text == ""
    child, reversed_child, items, mapping = value.child, value.reversed_child, value.items, value.mapping
    if child is None or reversed_child is None or items is None or mapping is None:
        raise AssertionError("Optional members were discarded")
    assert child.value == 1 and reversed_child.value == 2
    assert items[0].value == 3 and mapping[4] == "four"
    assert OptionalValues.model_validate_json(value.model_dump_json()).model_dump_json() == value.model_dump_json()
    nulls = OptionalValues.model_validate_json(
        '{"count":null,"text":null,"child":null,"reversed_child":null,"items":null,"mapping":null}')
    assert nulls.model_dump_json() == empty.model_dump_json()
    empty_containers = OptionalValues.model_validate_json('{"count":0,"items":[],"mapping":{}}')
    assert empty_containers.count == 0
    assert empty_containers.items is not None and empty_containers.mapping is not None
    strict = StrictValues.model_validate_json('{"count":7,"mapping":{"4":"four"}}')
    assert strict.count == 7
    strict_mapping = strict.mapping
    if strict_mapping is None:
        raise AssertionError("JSON key coercion was lost")
    assert strict_mapping[4] == "four"
    choice = OptionalChoice.model_validate_json('{"child":{"value":4,"description":"kept"}}')
    assert '"description":"kept"' in choice.model_dump_json()
    assert OptionalChoice.model_validate_json('{"child":null}').child is None


@pytest.mark.pyjs_web
@js
def test_optional_values_still_reject_invalid_concrete_members():
    for source in ['{"count":"invalid"}', '{"child":{}}', '{"reversed_child":4}',
                   '{"items":[{"value":"invalid"}]}', '{"mapping":{"invalid":"four"}}']:
        rejected = False
        try:
            OptionalValues.model_validate_json(source)
        except ValueError:
            rejected = True
        assert rejected
    rejected = False
    try:
        StrictValues.model_validate_json('{"count":"7"}')
    except ValueError:
        rejected = True
    assert rejected


def test_optional_contract_matches_python():
    test_optional_values_preserve_defaults_coercion_and_nested_models()
    test_optional_values_still_reject_invalid_concrete_members()


def test_valid_optional_models_do_not_construct_speculative_type_errors():
    source = '''
from tests.lib.test_pydantic_optional import OptionalValues

def main() -> int:
    for index in range(100):
        empty = OptionalValues.model_validate_json('{}')
        assert empty.child is None
        value = OptionalValues.model_validate_json(
            '{"count":7,"text":"ok","child":{"value":1},'
            '"reversed_child":{"value":2},"items":[{"value":3}],"mapping":{"4":"four"}}')
        assert value.count == 7
    return 100
'''
    with compile_source(source, filename="optional_validation.py") as compilation:
        javascript = compilation.javascript
    result = Node().run_javascript(javascript + '''
const original = globalThis.TypeError;
let errors = 0;
globalThis.TypeError = new Proxy(original, {
    construct(target, argumentsList, newTarget) {
        errors++;
        return Reflect.construct(target, argumentsList, newTarget);
    }
});
try {
    if (__pyjsEntry__.main() !== 100) throw new Error('Incomplete validation');
} finally {
    globalThis.TypeError = original;
}
console.log(errors);
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0", result.stdout
