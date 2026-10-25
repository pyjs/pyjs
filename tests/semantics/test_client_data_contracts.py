import pytest

from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    DICTIONARY_POP_CONTRACT,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
    NARROWED_METHOD_CONTRACT,
    REPLACED_ATTRIBUTE_CONTRACT,
)
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT, DICTIONARY_POP_CONTRACT], ids=["truth", "split", "pop"])
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
