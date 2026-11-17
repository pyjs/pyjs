import pytest

from tests.backend_semantics import DICTIONARY_ITEMS_CONTRACT, DICTIONARY_KEYS_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_dictionary_keys_contract():
    assert_semantics(DICTIONARY_KEYS_CONTRACT.print_source + "\nmain()\n")


def test_shared_dictionary_items_contract():
    assert_semantics(DICTIONARY_ITEMS_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.xfail(strict=True, reason="JS dictionary item views are exhausted after one iteration")
def test_item_view_can_be_iterated_repeatedly():
    assert_semantics('''
from pyjs import js
@js
def main():
    mapping = {"key": 1}
    view = mapping.items()
    for key, value in view:
        print(key, value)
    for key, value in view:
        print(key, value)
main()
''')
