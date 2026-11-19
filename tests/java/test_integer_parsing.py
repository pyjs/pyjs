from textwrap import dedent

from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import run_jvm


def test_decimal_fast_path_and_unicode_fallback_match_python(tmp_path):
    values = ["0", "-0", "+0", "17", "-23", "+42", "0000123", "-0000123",
              "9223372036854775807", "-9223372036854775808", "0" * 1000,
              " 42 ", "\t-23\n", "1_234", "+0_0", "\u0085\u200342\u3000",
              "١٢٣", "１２３", "𝟙𝟚𝟛", "1٢𝟛", "-𝟙_２٣",
              "", "+", "-", " ", "1x", "x1", "1 2", "++1", "--1", "+-1",
              "_1", "1_", "1__2", "+_1", "1.0", "1e2", "0x10", "²", "①",
              "\x001", "1\x00", "\x1c1", "1\u200b", "−1"]
    assert_text_matches_python(dedent(f'''
        def main() -> str:
            result: list[str] = []
            for text in {values!r}:
                try:
                    result.append(str(int(text)))
                except ValueError:
                    result.append("invalid")
            return "|".join(result)
    '''), tmp_path)


def test_decimal_overflow_and_malformed_suffix_keep_exception_categories(tmp_path):
    values = ["9223372036854775808", "-9223372036854775809", "+9223372036854775808",
              "9" * 1000, " 9223372036854775808 ", "9_223_372_036_854_775_808",
              "９２２３３７２０３６８５４７７５８０８"]
    actual = run_jvm(dedent(f'''
        def main() -> str:
            for text in {values!r}:
                try:
                    int(text)
                    return "missing overflow"
                except OverflowError:
                    pass
                try:
                    int(text + "x")
                    return "missing invalid literal"
                except ValueError:
                    pass
            return "verified"
    '''), tmp_path)
    assert actual.returncode == 0, actual.stderr
    assert actual.stdout == "verified"
