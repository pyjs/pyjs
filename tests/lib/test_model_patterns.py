import re
from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model

from pyjs import js
from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.java.json_codegen import JSONCodegen
from pyjs.javascript.source import compile_source
from pyjs.lib.pydantic.patterns import (
    compile_pattern,
    decode_pattern,
    encode_pattern,
    matches_pattern,
)
from pyjs.lib.pydantic.v2 import _class_info
from tests.model_patterns_contract import (
    PATTERN_CASES,
    Badge,
    accepted,
    check_large_and_grouped_patterns,
    check_patterns,
)


def test_patterns_on_python():
    assert check_patterns() == "validated"


@pytest.mark.pyjs_web
@js
def test_patterns_in_browser():
    assert check_patterns() == "validated"


@pytest.mark.pyjs_web
@js
def test_large_and_grouped_patterns_in_browser():
    assert check_large_and_grouped_patterns() == "validated"


@pytest.mark.parametrize("setting", ["strip_whitespace", "to_lower", "to_upper"])
@pytest.mark.parametrize("location", ["model", "field"])
def test_pattern_string_transforms_are_explicitly_unsupported(setting, location):
    config = ConfigDict(**{"str_" + setting: True}) if location == "model" else ConfigDict()
    constraint = (Field(pattern="^z$") if location == "model"
                  else StringConstraints(pattern="^z$", **{setting: True}))
    model = create_model("Text", __config__=config, value=(Annotated[str, constraint], ...))
    with pytest.raises(TypeError, match="do not support string transformations"):
        _class_info(model)
    with pytest.raises(TypeError, match="do not support string transformations"):
        JSONCodegen().check_constraints(model.model_fields["value"], "value", model_config=config)


@pytest.mark.parametrize("pattern, values", PATTERN_CASES)
def test_portable_patterns_match_pydantic(pattern, values):
    program = compile_pattern(pattern)
    for value in values:
        assert matches_pattern(value, program) == accepted(pattern, value), (pattern, value)


def test_pattern_metadata_and_generated_codec():
    assert compile_pattern("^a{1,2}[^x]*$") == [
        [1, 1, 3], [0, 0, 0], [1, 0, 0], [1, 1, 1], [0, 97, 97], [1, 120, 120],
    ]
    assert _class_info(Badge).config["field_constraints"]["color"]["pattern"] == [
        [1, 1, 7], [0, 0, 0], *([[0, 0, 1]] * 6),
        [0, 35, 35], [0, 48, 57, 65, 70, 97, 102],
    ]
    generator = JSONCodegen()
    matcher = generator.type_name(matches_pattern)
    loader = generator.type_name(decode_pattern)
    error = generator.type_name(ValueError)
    generator.check_constraints(Badge.model_fields["color"], "color")
    assert generator.lines == [
        f"if not {matcher}(color, {loader}({encode_pattern(compile_pattern('^#[0-9a-fA-F]{6}$'))!r})):",
        f"    raise {error}('Invalid JSON field constraint: pattern')",
    ]


@pytest.mark.parametrize("pattern", [r"\d+", r"\w", r"\p{L}", "a|b", "(ab)+",
                                    "(?i)abc", "[a-z&&b]", "a*?", re.compile("abc")])
def test_unsupported_patterns_fail_in_both_client_codecs(pattern):
    class Model(BaseModel):
        value: str = Field(pattern=pattern)

    with pytest.raises(TypeError, match="[Cc]lient model pattern"):
        _class_info(Model)
    with pytest.raises(TypeError, match="[Cc]lient model pattern"):
        JSONCodegen().check_constraints(Model.model_fields["value"], "value")


def test_python_regex_mode_is_not_silently_reinterpreted():
    class Model(BaseModel):
        model_config = ConfigDict(regex_engine="python-re")
        value: str = Field(pattern="a$")

    assert Model(value="a\n").value == "a\n"
    with pytest.raises(TypeError, match="default rust-regex semantics"):
        _class_info(Model)
    with pytest.raises(TypeError, match="default rust-regex semantics"):
        JSONCodegen().decode_model(Model, "reader", "result", 0)


@pytest.mark.parametrize("annotation", [int, list[str], str | int])
def test_pattern_requires_a_string_field(annotation):
    class Model(BaseModel):
        value: annotation = Field(pattern="abc")

    with pytest.raises(TypeError, match="require str or str"):
        _class_info(Model)
    with pytest.raises(TypeError, match="require str or str"):
        JSONCodegen().check_constraints(Model.model_fields["value"], "value")


@pytest.mark.parametrize("pattern, message", [("a{257}", "256 matching states"),
                                             ("a" * 4097, "4096 characters")])
def test_pattern_program_size_is_bounded(pattern, message):
    with pytest.raises(TypeError, match=message):
        compile_pattern(pattern)


def test_repeated_character_classes_share_a_bounded_table():
    program = compile_pattern(r"^[A-Za-z0-9._%+\-]{1,255}$")
    assert program[0] == [1, 1, 255]
    assert len(program) == 257
    assert sum(len(row) for row in program) < 800
    encoded = encode_pattern(program)
    assert decode_pattern(encoded) == program
    assert len(encoded.encode("ascii")) < 2000


@pytest.mark.parametrize("backend", ["javascript", "jvm"])
def test_oversized_distinct_range_tables_have_a_focused_error(backend):
    # Separated code points cannot collapse into adjacent ranges.
    pattern = "[" + "".join(chr(0x1000 + index * 2) for index in range(1800)) + "]" + "a" * 255
    assert len(pattern) < 4096
    with pytest.raises(TypeError, match="exceeds 4096 program integers"):
        compile_pattern(pattern)
    source = f'''from pyjs import js
from pydantic import BaseModel, Field
@js
class Text(BaseModel):
    value: str = Field(pattern={pattern!r})
@js
def main() -> str:
    return Text.model_validate_json('{{"value":"x"}}').value
'''
    with pytest.raises(CompilationError) as caught:
        if backend == "jvm":
            transpile_jvm(source, filename="large_pattern.py")
        else:
            with compile_source(source, filename="large_pattern.py"):
                pass
    assert caught.value.diagnostic.primary.span.source.filename == "large_pattern.py"
    assert "PYJS2001" in str(caught.value)
