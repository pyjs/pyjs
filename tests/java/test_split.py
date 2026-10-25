import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python


def test_explicit_split_matches_python_and_returns_mutable_lists(tmp_path):
    assert_text_matches_python(r'''
def main() -> str:
    output: list[str] = []
    for text in ["", "a", "/", "a//b/", "é😀雪😀", "a.*b.*", "a\\Eb\\E"]:
        for separator in ["/", "😀", ".*", "\\E"]:
            for limit in [-2, -1, 0, 1, 2, 9223372036854775807]:
                parts = text.split(separator, limit)
                parts.append("end")
                output.append("|".join(parts))
    output.append("|".join("a/b/".split("/")))
    output.append("|".join("a/b/".split("/", maxsplit=1)))
    try:
        "text".split("")
    except ValueError as error:
        output.append(str(error))
    return ":".join(output)
''', tmp_path)


@pytest.mark.parametrize("expression", ['"a b".split()', '"a b".split(None)'])
def test_whitespace_split_has_an_explicit_boundary(expression):
    with pytest.raises(JVMUnsupported, match="requires an explicit string separator"):
        transpile_jvm(f"def main() -> int:\n    return len({expression})\n")
