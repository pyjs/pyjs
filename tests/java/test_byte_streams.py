from tests.java.test_exceptions import run_jvm


def test_byte_buffer_extraction_on_jvm(tmp_path):
    result = run_jvm('''
from tests.java.test_android_bitmaps import (
    test_byte_buffer_extraction_returns_an_independent_binary_copy,
)
def main() -> str:
    test_byte_buffer_extraction_returns_an_independent_binary_copy()
    return "binary copy preserved"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "binary copy preserved"
