import pytest

from tests.java.test_exceptions import run_jvm


@pytest.mark.parametrize("case", [
    "base64_binary_round_trip",
    "base64_invalid_input_is_catchable",
    "digest_chunks_reset_and_reuse",
    "unavailable_digest_is_catchable",
])
def test_byte_codecs_on_jvm(case, tmp_path):
    result = run_jvm(f'''
from tests.java.test_android_byte_codecs import test_{case}
def main() -> str:
    test_{case}()
    return "ok"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"
