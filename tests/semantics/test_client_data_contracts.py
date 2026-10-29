import pytest

from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    BENCHMARK_PRIMITIVE_CONTRACTS,
    DICTIONARY_POP_CONTRACT,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
    LOCAL_COLLECTION_CONTRACT,
    NARROWED_METHOD_CONTRACT,
    RECEIVER_DOMAIN_CONTRACTS,
    REPLACED_ATTRIBUTE_CONTRACT,
    REPLACED_RECEIVER_CONTRACTS,
)
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("contract", BENCHMARK_PRIMITIVE_CONTRACTS.values(), ids=BENCHMARK_PRIMITIVE_CONTRACTS)
def test_benchmark_primitive_contract(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT, DICTIONARY_POP_CONTRACT, LOCAL_COLLECTION_CONTRACT], ids=["truth", "split", "pop", "local-collections"])
def test_client_data_contract(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


def test_awaited_values_preserve_instance_attributes():
    assert_semantics(AWAIT_ATTRIBUTE_SOURCE + '''
import asyncio
@js
async def main() -> None:
    print(await await_attributes())
asyncio.run(main())
''')


def test_narrowed_receivers_and_arguments_keep_their_refined_type():
    assert_semantics(NARROWED_METHOD_CONTRACT.print_source + "\nmain()\n")


def test_replaced_attributes_do_not_keep_stale_refinements():
    assert_semantics(REPLACED_ATTRIBUTE_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("contract", REPLACED_RECEIVER_CONTRACTS.values(), ids=REPLACED_RECEIVER_CONTRACTS)
def test_replaced_receivers_keep_base_declarations_reachable(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


@pytest.mark.parametrize("contract", RECEIVER_DOMAIN_CONTRACTS.values(), ids=RECEIVER_DOMAIN_CONTRACTS)
def test_virtual_bindings_use_the_stored_receiver_domain(contract):
    assert_semantics(contract.print_source + "\nmain()\n")
