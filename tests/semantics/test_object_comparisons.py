import pytest

from tests.backend_semantics import (
    ERASED_EQUALITY_CONTRACT,
    OBJECT_COMPARISON_CONTRACT,
    OBJECT_ORDERING_CONTRACT,
    nominal_alias_comparison_contract,
)

from .helpers import assert_semantics


@pytest.mark.parametrize("name", ["Box", "object"])
def test_root_equality_keeps_alias_callbacks_but_container_items_use_identity(name):
    assert_semantics(nominal_alias_comparison_contract(name).print_source + "\nmain()\n")


def test_shared_object_comparison_contract():
    assert_semantics(OBJECT_COMPARISON_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.xfail(strict=True, reason="JS object-typed == still emits identity instead of value equality")
def test_shared_erased_equality_contract():
    assert_semantics(ERASED_EQUALITY_CONTRACT.print_source + "\nmain()\n")


def test_shared_object_ordering_contract():
    assert_semantics(OBJECT_ORDERING_CONTRACT.print_source + "\nmain()\n")
