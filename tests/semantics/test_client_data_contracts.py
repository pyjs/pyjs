import pytest

from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    DICTIONARY_POP_CONTRACT,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
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
