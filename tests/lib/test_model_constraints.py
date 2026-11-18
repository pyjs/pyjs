from datetime import date

import pytest
from pydantic import BaseModel, Field

from pyjs import js
from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.javascript.source import compile_source
from pyjs.lib.pydantic.constraints import field_constraints
from pyjs.lib.pydantic.v2 import _class_info
from tests.model_constraints_contract import (
    Entry,
    GroupedBounds,
    OverrideBounds,
    Unconstrained,
    check_constraints,
    check_duplicate_constraints,
    check_grouped_constraints,
)


@js
class DatedEntry(BaseModel):
    day: date = Field(ge=date(2020, 1, 1))
    title: str = Field(min_length=1)


@js
class ChildDatedEntry(DatedEntry):
    pass


@pytest.mark.pyjs_web
@js
def test_nonnumeric_bound_does_not_prevent_model_compilation():
    entry = ChildDatedEntry.model_validate_json('{"day":"2021-05-01","title":"x"}')
    assert entry.title == "x"


def test_nonnumeric_bounds_remain_server_only():
    assert _class_info(DatedEntry).config == {
        "field_constraints": {"title": {"min_length": 1}},
    }


def test_grouped_metadata_preserves_bounds_and_override_order():
    assert _class_info(GroupedBounds).config == {
        "field_constraints": {
            "title": {"min_length": 1, "max_length": 2},
            "tags": {"min_length": 1, "max_length": 2},
            "count": {"ge": 0, "lt": 5},
        },
    }
    assert _class_info(OverrideBounds).config == _class_info(GroupedBounds).config


@pytest.mark.parametrize("backend", ["javascript", "jvm"])
@pytest.mark.parametrize("setting", ["strip_whitespace", "to_lower", "to_upper"])
@pytest.mark.parametrize("location", ["model", "field"])
def test_transformed_text_constraints_have_a_compilation_diagnostic(backend, setting, location):
    config = f"ConfigDict(str_{setting}=True)" if location == "model" else "ConfigDict()"
    field = ("str = Field(max_length=1)" if location == "model"
             else f"Annotated[str, StringConstraints({setting}=True, max_length=1)]")
    source = f'''from pyjs import js
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
@js
class Text(BaseModel):
    model_config = {config}
    value: {field}
@js
def main() -> str:
    return Text.model_validate_json('{{"value":" Z "}}').value
'''
    message = "Client model field constraints do not support string transformations"
    if backend == "jvm" and location == "model":
        message = "Unsupported JVM client model configuration: str_" + setting
    elif backend == "jvm":
        message = "JVM client models support typed construction and fields, not model operations"
    with pytest.raises(CompilationError, match=message) as caught:
        if backend == "jvm":
            transpile_jvm(source, filename="transforms.py")
        else:
            with compile_source(source, filename="transforms.py"):
                pass
    assert caught.value.diagnostic.primary.span.source.filename == "transforms.py"


def test_disabled_transforms_and_numeric_bounds_do_not_conflict():
    from typing import Annotated

    from pydantic import ConfigDict, StringConstraints, create_model

    model = create_model("Settings", __config__=ConfigDict(str_strip_whitespace=True),
                         value=(Annotated[str, StringConstraints(strip_whitespace=False, min_length=1)], ...),
                         count=(int, Field(ge=0)),
                         tags=(list[str], Field(min_length=1)),
                         lookup=(dict[str, str], Field(max_length=2)))
    assert field_constraints(model.model_fields["value"], model_config=model.model_config) == {"min_length": 1}
    assert field_constraints(model.model_fields["count"], model_config=model.model_config) == {"ge": 0}
    assert field_constraints(model.model_fields["tags"], model_config=model.model_config) == {"min_length": 1}
    assert field_constraints(model.model_fields["lookup"], model_config=model.model_config) == {"max_length": 2}


@pytest.mark.pyjs_web
@js
def test_grouped_constraints_in_browser():
    assert check_grouped_constraints() == "validated"


@pytest.mark.pyjs_web
@js
def test_duplicate_constraints_in_browser():
    assert check_duplicate_constraints() == "validated"


def test_json_field_constraints_on_python():
    assert check_constraints() == "validated"


def test_client_constraint_metadata_preserves_bounds_and_cleared_overrides():
    assert _class_info(Entry).config == {
        "extra": "forbid", "strict": True,
        "field_constraints": {
            "title": {"min_length": 1, "max_length": 2},
            "count": {"ge": 0, "le": 10},
            "ratio": {"gt": -1.5, "lt": 2.5},
            "optional": {"ge": 1},
            "caption": {"min_length": 1, "max_length": 2},
            "unchecked_default": {"ge": 0},
        },
    }
    assert _class_info(Unconstrained).config == {"field_constraints": {}}


@pytest.mark.pyjs_web
@js
def test_json_field_constraints_in_browser():
    assert check_constraints() == "validated"
