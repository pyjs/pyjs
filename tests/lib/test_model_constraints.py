import pytest

from pyjs import js
from pyjs.lib.pydantic.v2 import _class_info
from tests.model_constraints_contract import Entry, Unconstrained, check_constraints


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
