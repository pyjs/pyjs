import pytest

from tests.backend_semantics import (
    LITERAL_STRING_CONTRACT,
    TEXT_EDIT_CONTRACT,
    UNICODE_CHARACTER_CONTRACT,
    UNICODE_TEXT_CONTRACT,
)
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("contract", (UNICODE_TEXT_CONTRACT, UNICODE_CHARACTER_CONTRACT, TEXT_EDIT_CONTRACT, LITERAL_STRING_CONTRACT),
                         ids=("unicode", "characters", "editing", "literals"))
def test_shared_unicode_text_contract(contract):
    assert_semantics(contract.print_source + "\nmain()")
