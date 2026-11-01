import pytest

from tests.backend_semantics import LIST_BOOL_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_list_bool_contract():
    assert_semantics(LIST_BOOL_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize(("annotation", "empty", "full"), [
    ("list[int]", "[]", "[0]"), ("tuple[int, ...]", "()", "(0,)"),
    ("dict[str, int]", "{}", '{"key": 0}'), ("set[int]", "set()", "{0}"),
    ("str", '""', '"text"'), ("float", "0.0", "float('nan')"),
])
def test_bool_composes_with_negation_comparison_and_conditional_arguments(annotation, empty, full):
    assert_semantics(f'''
from pyjs import js
@js
def check(value: {annotation}) -> str:
    return str(not bool(value)) + ":" + str(bool(value) == False)
@js
def main():
    empty: {annotation} = {empty}
    full: {annotation} = {full}
    for populated in [False, True]:
        value = full if populated else empty
        print(check(value))
        print(not bool(full if populated else empty))
main()
''')


def test_typed_dictionary_bool_grouping():
    assert_semantics('''
from typing import TypedDict
from pyjs import js
class Fields(TypedDict, total=False):
    value: int
@js
def main():
    empty: Fields = {}
    full: Fields = {"value": 0}
    print(not bool(empty), not bool(full), bool(full) == False)
main()
''')
