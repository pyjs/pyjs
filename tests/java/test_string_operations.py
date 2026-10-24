from textwrap import dedent

import pytest

from pyjs.java import JVMUnsupported, read_jvm_class, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python


@pytest.mark.parametrize("expression", [
    '"".replace("", "x")',
    '"aaaa".replace("aa", "x")',
    '"aaaa".replace("aa", "x", 1)',
    '"😀a😀".replace("", "|", 2)',
    '"😀a😀".replace("", "|", 0)',
    '"😀a😀".replace("😀", "雪", count=1)',
    '"aaa".replace("a", "", -2)',
    '"aaa".replace("a", "x", True)',
    '"abc".replace("longer", "x")',
    '"abc".replace("", "x", 9223372036854775807)',
    'hex(-9223372036854775808)',
    'hex(9223372036854775807)',
    'hex(0)',
    'hex(True)',
    'str(ord("😀"))',
    'str(ord("雪"))',
    'str(ord("\\ud800"))',
    '"😀".replace("\\ud83d", "wrong")',
    '"😀".replace("\\ude00", "wrong")',
    '"a😀雪z"[1:-1]',
    '"a😀雪z"[-100:100]',
    '"a😀雪z"[:]',
    '"a😀雪z"[3:1]',
    '"a😀雪z"[9223372036854775807:]',
    '"a😀雪z"[-9223372036854775808:-9223372036854775808]',
])
def test_string_operations_match_python(tmp_path, expression):
    assert_text_matches_python(f"def main() -> str:\n    return {expression}\n", tmp_path)


@pytest.mark.parametrize("text", ["", "a", "😀雪a", "\ud800a"])
def test_iteration_visits_code_points_once_and_supports_loop_control(tmp_path, text):
    assert_text_matches_python(dedent(f'''
        def main() -> str:
            source = {text!r}
            result = ""
            for item in source:
                source = "reassigned"
                if item == "雪":
                    continue
                result += hex(ord(item)) + ":"
            else:
                result += "done"
            for item in "😀later":
                result += hex(ord(item))
                break
            return result
    '''), tmp_path)


@pytest.mark.parametrize("text", ["", "ab", "a😀"])
def test_ord_rejects_wrong_length_with_python_category(tmp_path, text):
    assert_text_matches_python(dedent(f'''
        def main() -> str:
            try:
                ord({text!r})
            except TypeError:
                return "rejected"
            return "incorrect"
    '''), tmp_path)


@pytest.mark.parametrize("step", ["2", "-1", "0", "step"])
def test_non_unit_string_slice_has_a_focused_boundary(step):
    with pytest.raises(JVMUnsupported, match="string slices currently require a unit step"):
        transpile_jvm(f'''
            def slice_text(text: str, step: int) -> str:
                return text[::{step}]
            def main() -> str:
                return slice_text("abc", 1)
        ''')


def test_named_builtins_do_not_confuse_user_functions(tmp_path):
    assert_text_matches_python('''
def hex(value: int) -> str:
    return "custom" + str(value)
def ord(value: str) -> int:
    return 7
def main() -> str:
    return hex(ord("😀"))
''', tmp_path)


@pytest.mark.parametrize(("return_type", "expression", "helpers"), [
    ("int", "42", set()),
    ("int", 'ord("😀")', {"pyjs_string_ord"}),
    ("str", "hex(-1)", {"pyjs_string_hex"}),
    ("str", '"😀x"[:1]', {"pyjs_string_slice"}),
    ("str", '"😀x".replace("", "!")', {"pyjs_string_replace", "pyjs_string_boundary"}),
])
def test_string_helpers_are_emitted_only_when_reachable(return_type, expression, helpers):
    compilation = transpile_jvm(f"def main() -> {return_type}:\n    return {expression}\n")
    main = read_jvm_class(compilation.classes["PyjsProgram"])
    assert {method.name for method in main.methods if method.name.startswith("pyjs_string_")} == helpers
