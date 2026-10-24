from pyjs.java import read_jvm_class, transpile_jvm
from tests.backend_semantics import UNICODE_CHARACTER_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


def test_shared_unicode_character_contract(tmp_path):
    assert_matches_python(UNICODE_CHARACTER_CONTRACT.source, tmp_path)


def test_chr_preserves_code_points_and_python_range_errors(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    for value in [0, 65, 127, 128, 233, 55296, 56319, 56320, 57343, 65535,
                  65536, 128512, 1114111]:
        assert ord(chr(value)) == value
        assert len(chr(value)) == 1
    assert ord(chr(True)) == 1 and ord(chr(False)) == 0
    for invalid in [-9223372036854775808, -2147483649, -2147483648, -1, 1114112,
                    2147483647, 2147483648, 9223372036854775807]:
        try:
            chr(invalid)
        except ValueError as error:
            assert str(error) == "chr() arg not in range(0x110000)"
        else:
            return "range not checked"
    return "matched"
''', tmp_path)


def test_chr_helper_is_demand_driven():
    compilation = transpile_jvm('def main() -> str:\n    return "plain"\n')
    methods = read_jvm_class(compilation.classes["PyjsProgram"]).methods
    assert not any(method.name == "pyjs_string_chr" for method in methods)
