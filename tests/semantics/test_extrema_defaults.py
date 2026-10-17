from tests.backend_semantics import REPRESENTED_EXTREMA_DEFAULT_CONTRACT

from .helpers import assert_semantics


def test_extrema_defaults_preserve_numeric_representations():
    assert_semantics(REPRESENTED_EXTREMA_DEFAULT_CONTRACT.print_source + "\nmain()\n")
