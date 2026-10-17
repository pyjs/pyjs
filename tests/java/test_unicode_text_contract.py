from tests.backend_semantics import UNICODE_TEXT_CONTRACT
from tests.java.test_native_boundaries import run_jvm


def test_shared_unicode_text_contract(tmp_path):
    result = run_jvm(UNICODE_TEXT_CONTRACT.source, tmp_path)
    assert result.returncode == 0, result.stderr or UNICODE_TEXT_CONTRACT.failure(result.returncode)
