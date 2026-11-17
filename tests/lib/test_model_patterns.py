import re

import pytest
from pydantic import BaseModel, ConfigDict, Field

from pyjs import js
from pyjs.java.json_codegen import JSONCodegen
from pyjs.lib.pydantic.patterns import compile_pattern, matches_pattern
from pyjs.lib.pydantic.v2 import _class_info
from tests.model_patterns_contract import PATTERN_CASES, Badge, accepted, check_patterns


def test_patterns_on_python():
    assert check_patterns() == "validated"


@pytest.mark.pyjs_web
@js
def test_patterns_in_browser():
    assert check_patterns() == "validated"


@pytest.mark.parametrize("pattern, values", PATTERN_CASES)
def test_portable_patterns_match_pydantic(pattern, values):
    program = compile_pattern(pattern)
    for value in values:
        assert matches_pattern(value, program) == accepted(pattern, value), (pattern, value)


def test_pattern_metadata_and_generated_codec():
    assert compile_pattern("^a{1,2}[^x]*$") == [
        [1, 1], [0, 0, 0, 97, 97], [1, 0, 0, 97, 97], [1, 1, 1, 120, 120],
    ]
    assert _class_info(Badge).config["field_constraints"]["color"]["pattern"] == [
        [1, 1], [0, 0, 0, 35, 35], *([[0, 0, 0, 48, 57, 97, 102, 65, 70]] * 6),
    ]
    generator = JSONCodegen()
    matcher = generator.type_name(matches_pattern)
    error = generator.type_name(ValueError)
    generator.check_constraints(Badge.model_fields["color"], "color")
    assert generator.lines == [
        f"if not {matcher}(color, {compile_pattern('^#[0-9a-fA-F]{6}$')!r}):",
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
