from tests.backend_semantics import TUPLE_ITERATOR_DEFAULT_CONTRACT

from .helpers import assert_semantics


def test_tuple_iterator_defaults_preserve_identity_and_representation():
    assert_semantics(TUPLE_ITERATOR_DEFAULT_CONTRACT.print_source + "\nmain()\n")
