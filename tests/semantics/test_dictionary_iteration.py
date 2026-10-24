from tests.backend_semantics import DICTIONARY_KEYS_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_dictionary_keys_contract():
    assert_semantics(DICTIONARY_KEYS_CONTRACT.print_source + "\nmain()\n")
