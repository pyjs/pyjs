import pytest

from tests.java.test_exceptions import run_jvm


@pytest.mark.parametrize("case", [
    "strict_utf8_reads_small_chunks_without_losing_unicode",
    "strict_utf8_rejects_malformed_and_truncated_input",
    "reader_ranges_and_string_copy",
    "empty_utf8_input_is_eof",
])
def test_text_input_on_jvm(case, tmp_path):
    result = run_jvm(f'''
from tests.java.test_android_text_input import test_{case}
def main() -> str:
    test_{case}()
    return "ok"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"
