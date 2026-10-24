import json

import pytest
from pydantic import BaseModel, create_model

from pyjs.java.json_codegen import JSONCodegen
from tests.java.json_models import Empty, Item, OptionalField, Page
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex


def codec_source(annotation):
    generator = JSONCodegen()
    generator.validate(annotation)
    generator.emit("reader = _pyjs_reader(source)")
    value = generator.decode(annotation, "reader")
    generator.emit("reader.finish()")
    generator.emit("parts: list[str] = []")
    generator.encode(annotation, value, "parts")
    generator.emit("return ''.join(parts)")
    imports = [f"from {value.__module__} import {value.__name__} as {name}"
               for name, value in generator.imports.items()]
    body = "\n".join("    " + line for line in generator.lines)
    return "\n".join(imports) + "\n\ndef roundtrip(source: str) -> str:\n" + body + "\n"


def model_corpus():
    source = codec_source(Page)
    document = {
        "items": [{"name": "snow 雪😀"}, {"name": "line\nnext", "count": 9007199254740993}],
        "scores": {"first": 1.25, "missing": None},
        "cursor": None,
        "unknown": {"nested": [1, {"more": "ignored"}]},
    }
    expected = Page.model_validate(document).model_dump_json()
    # The JVM writer uses ASCII escapes; compare the canonical decoded value.
    expected = json.dumps(json.loads(expected), ensure_ascii=True, separators=(",", ":"))
    invalid = [
        "null", "[]", "{}", '{"items":[],"scores":null}',
        '{"items":null,"scores":{}}', '{"items":[],"scores":{},"mode":"bad"}',
        '{"items":[],"scores":{},"enabled":1}',
        '{"items":[{"name":"x","extra":1}],"scores":{}}',
        '{"items":[{}],"scores":{}}',
        '{"items":[],"scores":{"value":1e999}}',
        '{"items":[],"scores":{},"cursor":9223372036854775808}',
        json.dumps(document) + "garbage",
    ]
    source += f'''
def main() -> str:
    assert roundtrip({json.dumps(document)!r}) == {expected!r}
    for invalid in {invalid!r}:
        try:
            roundtrip(invalid)
        except ValueError:
            continue
        return "accepted invalid JSON: " + invalid
    return "matched"
'''
    return source


def test_generated_model_codecs_match_python(tmp_path):
    assert_text_matches_python(model_corpus(), tmp_path)


def test_generated_model_codecs_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(model_corpus(), tmp_path)


def test_generated_encoder_reads_subclasses_through_base_model_fields(tmp_path):
    generator = JSONCodegen()
    generator.validate(list[Item])
    generator.emit("parts: list[str] = []")
    generator.encode(list[Item], "values", "parts")
    generator.emit("return ''.join(parts)")
    body = "\n".join("    " + line for line in generator.lines)
    assert_text_matches_python('''
from tests.java.json_models import Item, ChildItem
from pyjs.java.json import quote as _pyjs_quote
def encode(values: list[Item]) -> str:
''' + body + '''
def main() -> str:
    value = ChildItem(name="hello")
    encoded = encode([value])
    assert encoded == '[{"name":"hello","count":5}]'
    return encoded
''', tmp_path)


@pytest.mark.parametrize(("annotation", "source", "expected"), [
    (OptionalField, '{"value":null}', '{"value":null}'),
    (OptionalField, '{"value":0}', '{"value":0}'),
    (Empty, '{"ignored":[1,true]}', '{}'),
    (Item, '{"name":"first","name":"last"}', '{"name":"last","count":0}'),
    (list[int | None], '[1,null,0]', '[1,null,0]'),
    (dict[str, bool], '{"x":true,"y":false}', '{"x":true,"y":false}'),
])
def test_generated_codecs_host_cases(annotation, source, expected):
    namespace = {}
    exec(codec_source(annotation), namespace)
    assert namespace["roundtrip"](source) == expected


def test_required_nullable_field_is_not_an_optional_field():
    namespace = {}
    exec(codec_source(OptionalField), namespace)
    with pytest.raises(ValueError, match="Missing JSON model field: value"):
        namespace["roundtrip"]("{}")


@pytest.mark.parametrize("annotation", [int | float, list, dict[int, str], tuple[str], object])
def test_unsupported_codec_schema_is_explicit(annotation):
    with pytest.raises(TypeError, match="Unsupported JVM JSON schema"):
        JSONCodegen().validate(annotation)


def test_recursive_codec_schema_is_explicit():
    class Node(BaseModel):
        child: Node | None = None
    with pytest.raises(TypeError, match="schemas must be acyclic"):
        JSONCodegen().validate(Node)


def test_repeated_schema_graphs_have_bounded_generated_source():
    schema = Item
    for depth in range(12):
        schema = create_model(f"Pair{depth}", left=(schema, ...), right=(schema, ...))
    generator = JSONCodegen()
    generator.validate(schema)
    assert len(generator.schema_heights) == 15
    with pytest.raises(TypeError, match="generated-source limit"):
        generator.encode(schema, "value", "parts")
    assert len(generator.lines) == 4096


@pytest.mark.parametrize("depth", [32, 1100])
def test_deep_schema_is_rejected_before_emission(depth):
    schema = str
    for _ in range(depth):
        schema = list[schema]
    generator = JSONCodegen()
    with pytest.raises(TypeError, match="at most 32 levels"):
        generator.validate(schema)
    assert generator.lines == []


def test_generated_float_encoder_rejects_nonfinite_values_on_jvm(tmp_path):
    generator = JSONCodegen()
    generator.validate(float)
    generator.emit("parts: list[str] = []")
    generator.encode(float, "value", "parts")
    generator.emit("return ''.join(parts)")
    body = "\n".join("    " + line for line in generator.lines)
    assert_text_matches_python('''from pyjs.java import parse_double
from pyjs.java import double_to_string as _pyjs_double
def encode(value: float) -> str:
''' + body + '''
def main() -> str:
    assert encode(-0.0) == "-0.0"
    for token in ["NaN", "Infinity", "-Infinity"]:
        try:
            encode(parse_double(token))
        except ValueError:
            continue
        return "encoded a nonfinite float"
    return "matched"
''', tmp_path)
