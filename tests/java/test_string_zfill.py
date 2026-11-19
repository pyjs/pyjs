from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, read_jvm_class, transpile_jvm
from tests.backend_semantics import STRING_ZFILL_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


def test_shared_zfill_contract(tmp_path):
    assert_matches_python(STRING_ZFILL_CONTRACT.source, tmp_path)


def test_zfill_matches_python_for_signs_unicode_and_width_boundaries(tmp_path):
    assert_text_matches_python(dedent('''
        def main() -> str:
            result = ""
            for text in ["", "7", "-12", "+12", "+", "-", "--1", " 7", "−7",
                         "😀", "-😀", "e\\u0301", "雪😀"]:
                for width in [-9223372036854775808, -1, 0, 1, 2, 4, 8]:
                    result += "[" + text.zfill(width) + "]"
            return result + "".zfill(True) + "7".zfill(False)
    '''), tmp_path)


def test_zfill_evaluates_receiver_and_width_once_in_order(tmp_path):
    assert_text_matches_python(dedent('''
        def text(events: list[str]) -> str:
            events.append("text")
            return "-7"
        def width(events: list[str]) -> int:
            events.append("width")
            return 4
        def main() -> str:
            events: list[str] = []
            result = text(events).zfill(width(events))
            return result + ":" + ",".join(events)
    '''), tmp_path)


def test_zfill_rejects_unrepresentable_capacity_without_allocating(tmp_path):
    assert_text_matches_python(dedent('''
        def main() -> str:
            try:
                "7".zfill(9223372036854775807)
            except MemoryError:
                return "rejected"
            return "incorrect"
    '''), tmp_path)


@pytest.mark.parametrize("argument, error, message", [
    ("width=4", CompilationError, "positional"),
    ("4.0", JVMUnsupported, "one positional integer width"),
])
def test_zfill_rejects_invalid_argument_shapes(argument, error, message):
    with pytest.raises(error, match=message):
        transpile_jvm(f'def main() -> str:\n    return "7".zfill({argument})\n')


def test_zfill_helper_is_demand_driven():
    for expression, helpers in [('"7"', set()), ('"7".zfill(2)', {"pyjs_string_zfill"})]:
        result = transpile_jvm(f'def main() -> str:\n    return {expression}\n')
        main = read_jvm_class(result.classes["PyjsProgram"])
        assert {method.name for method in main.methods if method.name.startswith("pyjs_string_")} == helpers
