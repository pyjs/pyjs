from collections.abc import Callable
from typing import Annotated, TypedDict

import pytest

from pyjs import StaticArray, float32, int8, int64
from pyjs.analysis.representation import (
    ValueRepresentation,
    annotation_representation,
    array_representation,
    compound_representation,
    direct_representation,
    numeric_comparison_representations_compatible,
    tuple_representation,
)
from pyjs.analysis.value_representation import resolve_sum_numeric_format
from pyjs.numeric import ArrayFormat, NumericFormat

BYTE = NumericFormat("integer", 8, True)
LONG = NumericFormat("integer", 64, True)
SINGLE = NumericFormat("float", 32)
BYTE_PAIR = ArrayFormat(2, item_numeric=BYTE)
LONG_PAIR = ArrayFormat(2, item_numeric=LONG)
BYTE_VALUE = direct_representation(BYTE, None)
LONG_VALUE = direct_representation(LONG, None)
SINGLE_VALUE = direct_representation(SINGLE, None)
BYTE_LIST = compound_representation(arguments=(BYTE_VALUE,))
SINGLE_LIST = compound_representation(arguments=(SINGLE_VALUE,))


def sum_domain_case(name, expected, **changes):
    arguments = {
        "common_item": None,
        "possible_items": frozenset(),
        "ordinary_item_types": frozenset(),
        "start": None,
        "ordinary_float_start": False,
        "guaranteed_ordinary_float": False,
        "provably_nonempty": False,
    }
    for key in ("possible_items", "ordinary_item_types"):
        if key in changes:
            changes[key] = frozenset(changes[key])
    arguments.update(changes)
    return pytest.param(arguments, expected, id=name)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        sum_domain_case(
            "matching start resolves an empty iterable",
            (BYTE, None),
            common_item=BYTE,
            possible_items={BYTE},
            ordinary_item_types={"int"},
            start=BYTE,
        ),
        sum_domain_case(
            "nonempty fixed items select their format",
            (BYTE, None),
            common_item=BYTE,
            possible_items={BYTE},
            ordinary_item_types={"int"},
            provably_nonempty=True,
        ),
        sum_domain_case(
            "possibly empty fixed items are ambiguous",
            (None, "potentially_empty"),
            common_item=BYTE,
            possible_items={BYTE},
            ordinary_item_types={"int"},
        ),
        sum_domain_case(
            "ordinary float start selects ordinary arithmetic",
            (None, None),
            common_item=BYTE,
            possible_items={BYTE},
            ordinary_item_types={"int"},
            ordinary_float_start=True,
            provably_nonempty=True,
        ),
        sum_domain_case(
            "represented integer start governs ordinary integers",
            (BYTE, None),
            ordinary_item_types={"int"},
            start=BYTE,
        ),
        sum_domain_case(
            "represented float start governs ordinary integers",
            (SINGLE, None),
            ordinary_item_types={"int"},
            start=SINGLE,
        ),
        sum_domain_case(
            "guaranteed ordinary float overrides integer start",
            (None, None),
            ordinary_item_types={"float"},
            start=BYTE,
            guaranteed_ordinary_float=True,
            provably_nonempty=True,
        ),
        sum_domain_case(
            "possible ordinary float conflicts with integer start",
            (None, "ambiguous"),
            ordinary_item_types={"float"},
            start=BYTE,
        ),
        sum_domain_case(
            "matching start resolves possible fixed items",
            (BYTE, None),
            possible_items={BYTE},
            ordinary_item_types={"int"},
            start=BYTE,
        ),
        sum_domain_case(
            "represented float start absorbs ordinary floats",
            (SINGLE, None),
            possible_items={SINGLE},
            ordinary_item_types={"float"},
            start=SINGLE,
        ),
        sum_domain_case(
            "ordinary float start absorbs possible fixed integers",
            (None, None),
            possible_items={BYTE},
            ordinary_item_types={"int"},
            ordinary_float_start=True,
        ),
        sum_domain_case(
            "mixed represented items are ambiguous",
            (None, "ambiguous"),
            possible_items={BYTE, LONG},
            ordinary_item_types={"int"},
            provably_nonempty=True,
        ),
        sum_domain_case(
            "different represented start is incompatible",
            (None, "incompatible_start"),
            common_item=BYTE,
            possible_items={BYTE},
            ordinary_item_types={"int"},
            start=LONG,
            provably_nonempty=True,
        ),
    ),
)
def test_sum_numeric_domain_resolution_is_explicit(arguments, expected):
    assert resolve_sum_numeric_format(**arguments) == expected


@pytest.mark.parametrize(
    ("arguments", "exception", "message"),
    (
        (
            {"kind": "invalid"},
            ValueError,
            "unknown compound representation kind: invalid",
        ),
        (
            {"numeric": BYTE, "array": BYTE_PAIR},
            TypeError,
            "a value cannot have two direct representations",
        ),
        (
            {"kind": "tuple", "numeric": BYTE},
            TypeError,
            "a direct representation cannot have a compound kind",
        ),
        (
            {"arguments": (BYTE_VALUE,)},
            TypeError,
            "compound members require a compound representation kind",
        ),
        (
            {"fields": (("value", None),)},
            TypeError,
            "record fields require a record representation",
        ),
        (
            {"kind": "record", "fields": (("", None),)},
            TypeError,
            "record representation fields require names",
        ),
        (
            {
                "kind": "record",
                "fields": (("value", BYTE_VALUE), ("value", LONG_VALUE)),
            },
            TypeError,
            "record representation fields must be unique",
        ),
        (
            {"kind": "record", "arguments": (None,)},
            TypeError,
            "a record representation cannot have generic members",
        ),
        (
            {"numeric": BYTE, "arguments": (None,)},
            TypeError,
            "a direct representation cannot also describe a compound value",
        ),
        (
            {"array": BYTE_PAIR, "arguments": (None, None)},
            TypeError,
            "an array representation accepts only one represented item",
        ),
        (
            {"kind": "tuple", "parameters": ()},
            TypeError,
            "tuple and union representations accept only arguments",
        ),
        (
            {"kind": "union", "result": BYTE_VALUE},
            TypeError,
            "tuple and union representations accept only arguments",
        ),
        (
            {
                "kind": "generic",
                "arguments": (BYTE_VALUE,),
                "result": BYTE_VALUE,
            },
            TypeError,
            "a generic representation cannot be both a container and callable",
        ),
    ),
)
def test_value_representation_rejects_incompatible_shapes(
    arguments,
    exception,
    message,
):
    with pytest.raises(exception, match=message):
        ValueRepresentation(**arguments)


@pytest.mark.parametrize(
    ("representation", "item"),
    (
        (array_representation(BYTE_PAIR), BYTE_VALUE),
        (
            array_representation(BYTE_PAIR, BYTE_LIST),
            BYTE_LIST,
        ),
        (BYTE_LIST, BYTE_VALUE),
        (
            tuple_representation((BYTE_VALUE, BYTE_VALUE)),
            BYTE_VALUE,
        ),
        (
            tuple_representation((BYTE_VALUE, LONG_VALUE)),
            None,
        ),
        (
            compound_representation(
                kind="union",
                arguments=(
                    compound_representation(arguments=(LONG_VALUE,)),
                    tuple_representation((LONG_VALUE,)),
                ),
            ),
            LONG_VALUE,
        ),
    ),
)
def test_item_representation_requires_one_common_item(representation, item):
    assert representation.item_representation == item


def test_numeric_formats_walk_every_recursive_position():
    representation = compound_representation(
        kind="record",
        fields=(
            ("byte", BYTE_VALUE),
            (
                "callback",
                compound_representation(
                    parameters=(LONG_VALUE,),
                    result=SINGLE_VALUE,
                ),
            ),
            ("array", array_representation(BYTE_PAIR)),
        ),
    )

    assert representation.numeric_formats == {BYTE, LONG, SINGLE}


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    (
        (array_representation(BYTE_PAIR), None, True),
        (array_representation(BYTE_PAIR), BYTE_LIST, True),
        (array_representation(BYTE_PAIR), array_representation(BYTE_PAIR), True),
        (array_representation(BYTE_PAIR), LONG_VALUE, False),
        (array_representation(BYTE_PAIR), array_representation(LONG_PAIR), False),
    ),
)
def test_array_layout_is_transparent_to_numeric_comparison(
    left,
    right,
    expected,
):
    assert numeric_comparison_representations_compatible(left, right) is expected
    assert numeric_comparison_representations_compatible(right, left) is expected


def test_direct_numeric_formats_only_walk_union_alternatives():
    representation = compound_representation(
        kind="union",
        arguments=(
            BYTE_VALUE,
            compound_representation(
                kind="union",
                arguments=(LONG_VALUE, None),
            ),
            compound_representation(arguments=(SINGLE_VALUE,)),
        ),
    )

    assert representation.direct_numeric_formats == {BYTE, LONG}
    assert representation.numeric_formats == {BYTE, LONG, SINGLE}


@pytest.mark.parametrize("right,expected", [
    (BYTE_VALUE, True),
    (LONG_VALUE, False),
    (SINGLE_VALUE, False),
    (None, True),
    (compound_representation(kind="union", arguments=(None, BYTE_VALUE)), True),
    (compound_representation(kind="union", arguments=(None, LONG_VALUE)), False),
    (BYTE_LIST, False),
    (tuple_representation((BYTE_VALUE, None)), False),
])
def test_scalar_union_comparison_preserves_numeric_domains(right, expected):
    left = compound_representation(kind="union", arguments=(BYTE_VALUE, None))
    assert numeric_comparison_representations_compatible(left, right) is expected
    assert numeric_comparison_representations_compatible(right, left) is expected


class Row(TypedDict):
    value: int8
    samples: list[float32]


@pytest.mark.parametrize(
    ("annotation", "expected"),
    (
        (int8, BYTE_VALUE),
        (
            StaticArray[int8, 2],
            array_representation(BYTE_PAIR),
        ),
        (
            list[int64],
            compound_representation(arguments=(LONG_VALUE,)),
        ),
        (
            tuple[int8, int64],
            tuple_representation((BYTE_VALUE, LONG_VALUE)),
        ),
        (
            int8 | str,
            compound_representation(
                kind="union",
                arguments=(BYTE_VALUE, None),
            ),
        ),
        (
            Callable[[int8], float32],
            compound_representation(
                parameters=(BYTE_VALUE,),
                result=SINGLE_VALUE,
            ),
        ),
        (
            Row,
            compound_representation(
                kind="record",
                fields=(
                    ("value", BYTE_VALUE),
                    ("samples", SINGLE_LIST),
                ),
            ),
        ),
        (Annotated[list[int8], "values"], BYTE_LIST),
    ),
)
def test_annotations_build_recursive_representations(annotation, expected):
    assert annotation_representation(annotation) == expected
