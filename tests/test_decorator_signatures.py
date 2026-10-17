import annotationlib
from typing import Annotated

import pytest

from pyjs import js, llvm
from pyjs.decorators import (
    ParameterLifetime,
    configure_parameter_lifetimes,
    integer_index_parameters,
    native_operation,
    parameter_lifetimes,
)


def helper(value: int) -> int:
    return value


PARAMETER_DECORATORS = [
    pytest.param(lambda target: configure_parameter_lifetimes(target, {"value": ParameterLifetime.RETURNED}),
                 id="lifetime"),
    pytest.param(integer_index_parameters("value"), id="integer_index"),
    pytest.param(native_operation("test.relay", value=ParameterLifetime.RETURNED), id="native"),
    pytest.param(llvm.inline("{value}", value=ParameterLifetime.RETURNED), id="llvm_inline"),
    pytest.param(js.inline("{helper}({value})", helper=helper), id="js_inline"),
]


@pytest.mark.parametrize("decorate", PARAMETER_DECORATORS)
def test_parameter_name_validation_does_not_resolve_later_annotations(decorate):
    def relay(value: Alias) -> Box:
        return value

    assert decorate(relay) is relay

    class Box:
        pass

    Alias = Box
    assert annotationlib.get_annotations(relay) == {"value": Box, "return": Box}
    value = Box()
    assert relay(value) is value


@pytest.mark.parametrize("decorate", [
    lambda target: configure_parameter_lifetimes(target, {"value": ParameterLifetime.BORROWED}),
    integer_index_parameters("value"),
    js.inline("{helper}({value})", helper=helper),
])
def test_parameter_metadata_preserves_string_annotations(decorate):
    def relay(value: "UndefinedAlias") -> "UndefinedAlias":  # noqa: F821, UP037
        return value

    decorate(relay)
    assert annotationlib.get_annotations(relay) == {
        "value": "UndefinedAlias", "return": "UndefinedAlias",
    }


@pytest.mark.parametrize("decorate, message", [
    (lambda target: configure_parameter_lifetimes(target, {"typo": ParameterLifetime.RETURNED}),
     "parameter lifetime parameters do not exist: typo"),
    (integer_index_parameters("typo"), "integer-index parameters do not exist: typo"),
    (js.inline("{value}", value=helper), "conflict with call arguments: value"),
    (llvm.inline("{typo}"), "not a parameter"),
])
@pytest.mark.parametrize("formatted", [False, True])
def test_invalid_parameter_metadata_diagnoses_before_resolving_annotations(decorate, message, formatted):
    unit = "px"
    if formatted:
        def relay(value: Annotated[int, f"{unit}"]) -> int:
            return value
    else:
        def relay(value: Missing) -> Missing:  # noqa: F821
            return value

    with pytest.raises(TypeError, match=message):
        decorate(relay)


def test_bound_method_lifetime_metadata_keeps_lazy_annotations_and_immutability():
    class Owner:
        def relay(self, value: Alias) -> Alias:
            return value

    instance = Owner()
    configure_parameter_lifetimes(instance.relay, {"value": ParameterLifetime.RETURNED})
    Alias = Owner
    assert annotationlib.get_annotations(Owner.relay) == {"value": Owner, "return": Owner}
    contracts = parameter_lifetimes(instance.relay)
    assert contracts == parameter_lifetimes(Owner.relay) == {"value": ParameterLifetime.RETURNED}
    with pytest.raises(TypeError):
        contracts["value"] = ParameterLifetime.EXTERNAL
    with pytest.raises(TypeError, match="already has a parameter lifetime contract"):
        configure_parameter_lifetimes(instance.relay, {"value": ParameterLifetime.EXTERNAL})


@pytest.mark.parametrize("decorate", PARAMETER_DECORATORS)
@pytest.mark.parametrize("shape", ["format", "unpack", "forward_format", "dict_lookup", "list_lookup"])
def test_valid_metadata_expressions_survive_signature_stringifier_limits(decorate, shape):
    unit = "px"
    pairs = [(1, 2)]
    metadata = {"unit": "px"}
    if shape == "format":
        def relay(value: Annotated[int, f"{unit}"]) -> int:
            return value
    elif shape == "unpack":
        def relay(value: Annotated[int, [left for left, right in pairs]]) -> int:
            return value
    elif shape == "dict_lookup":
        def relay(value: Annotated[int, {**metadata}["unit"]]) -> int:
            return value
    elif shape == "list_lookup":
        def relay(value: Annotated[int, [*pairs][0]]) -> int:
            return value
    else:
        def relay(value: Annotated[Later, f"{unit}"]) -> Later:
            return value

    assert decorate(relay) is relay

    class Later:
        pass

    expected = (Annotated[Later, "px"] if shape == "forward_format" else
                Annotated[int, (1, 2)] if shape == "list_lookup" else
                Annotated[int, [1]] if shape == "unpack" else Annotated[int, "px"])
    assert annotationlib.get_annotations(relay)["value"] == expected


@pytest.mark.parametrize("decorate", PARAMETER_DECORATORS)
def test_signature_fallback_propagates_invalid_annotation_lookup(decorate):
    metadata = {"unit": "px"}

    def relay(value: Annotated[int, {**metadata}["missing"]]) -> int:
        return value

    with pytest.raises(KeyError, match="missing"):
        decorate(relay)


@pytest.mark.parametrize("invalid", ["signature", "wrapper_cycle"])
def test_signature_fallback_does_not_hide_invalid_callable_metadata(invalid):
    def relay(value: int) -> int:
        return value

    if invalid == "signature":
        relay.__signature__ = object()
        error, message = TypeError, "unexpected object.*__signature__"
    else:
        relay.__wrapped__ = relay
        error, message = ValueError, "wrapper loop"
    with pytest.raises(error, match=message):
        configure_parameter_lifetimes(relay, {"value": ParameterLifetime.RETURNED})


@pytest.mark.parametrize("decorate", PARAMETER_DECORATORS)
def test_stringifiable_annotations_still_resolve_after_later_rebinding(decorate):
    Alias = int

    def relay(value: Alias) -> Alias:
        return value

    decorate(relay)
    Alias = str
    assert annotationlib.get_annotations(relay) == {"value": str, "return": str}
