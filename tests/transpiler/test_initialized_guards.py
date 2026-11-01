import pytest

from pyjs.testing.helpers import ad, at, diagnostic_text


def test_compound_optional_initialization_preserves_exact_analyzed_and_javascript_source():
    at(
        '''
        def main(value: int | None, refresh: bool) -> int:
            if value is None or refresh:
                value = 7
            return value + 1
        ''',
        '''
        def main(value: int | None, refresh: bool) -> int:
            if value.[object]__is__!(None) or refresh:
                value = 7
            return value.[int]__add__!(1)
        ''',
        '''
        export function main(value, refresh) {
            if (value == null || refresh) {
                value = 7;
            }
            return value + 1;
        }
        ''',
    )


@pytest.mark.parametrize("body", [
    "if value is None and refresh:\n        value = 7",
    "if value is None or refresh:\n        value = None",
    "if value is None or refresh:\n        if refresh:\n            value = 7",
    "if value is None or refresh:\n        value = 7\n    else:\n        value = None",
    "if value is None or refresh:\n        value = 7\n        value = None",
])
def test_both_live_paths_must_establish_the_postcondition(body):
    source = ("def main(value: int | None, refresh: bool) -> int:\n    " + body
              + "\n    return value + 1\n")
    ad(source, diagnostic_text(
        "guard.py", len(source.splitlines()), "return value + 1", "       ^^^^^^^^^",
        "pyjs.CompilationError: Operator '+' is not supported for every combination "
        "of int|NoneType and int [PYJS1104]",
        "help: Narrow either operand before applying the operator.",
    ), filename="guard.py")
