import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import UNICODE_TEXT_CONTRACT


def test_shared_unicode_text_contract():
    result = LLVM().assert_matches_python(UNICODE_TEXT_CONTRACT.source)
    assert result.native.returncode == 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_unicode_case_and_properties_with_collection(optimize):
    methods = ("lower", "upper", "casefold", "swapcase", "title", "capitalize")
    predicates = ("isascii", "isalnum", "isalpha", "isdecimal", "isdigit",
                  "isnumeric", "isprintable", "islower", "isupper", "istitle", "isidentifier")
    values = ("", "A\0B", "İΣßﬃǄa界😀", "ΟΣ", "ΟΣΑ", "AΣ́", "AΣ́1", "AΣ'",
              "1Σ", "foóbar", "they're BILL'S", "١٢٣", "½²", "\u3000", "_abc", "á")
    operations = "\n".join(
        "                result += " + (f"value.{method}()" if method in methods
                                    else f"str(value.{method}())") + " + '|'"
        for method in (*methods, *predicates)
    )
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            result = ""
            for item in {list(values)!r}:
                value = item + ""
                gc_collect()
{operations}
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_unicode_searches_and_ordering(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            result = ""
            for value in ["", "a", "aa", "é😀é", "éé", "\\0é\\0", "\\u3000β", "\\U0010ffff"]:
                result += str(len(value)) + ":"
                for other in ["", "aa", "é", "😀", "́", "absent", "\\0"]:
                    result += str(other in value) + str(other not in value)
                    result += str(value.startswith(other)) + str(value.endswith(other))
                    result += str(value.find(other)) + str(value.rfind(other)) + str(value.count(other))
                    result += str(value == other) + str(value != other)
                    result += str(value < other) + str(value <= other)
                    result += str(value > other) + str(value >= other) + "|"
            return result
    ''', optimize=optimize)


def test_unicode_tables_are_only_emitted_for_reached_unicode_methods():
    for expression in ('len("é🙂")', 'int("é" in "café")', 'int("abc".isascii())'):
        assert "@pyjs.unicode." not in transpile_llvm(f"def main() -> int: return {expression}")
    source = transpile_llvm('def main() -> str: return "İΣ".lower()')
    assert source.count("define ptr @pyjs.unicode.change.case(") == 1
    assert "@pyjs.unicode.lower.mapping" in source


def test_string_keyword_boundary_has_a_focused_diagnostic():
    with pytest.raises(CompilationError, match="parameter 'prefix' is positional-only"):
        transpile_llvm('def main() -> int: return int("abc".startswith(prefix="a"))')


def test_lone_surrogate_literal_has_a_focused_diagnostic():
    with pytest.raises(LLVMUnsupported, match="lone surrogates"):
        transpile_llvm('def main() -> str: return "\\ud800"')
