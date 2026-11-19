import pytest

from tests.java.test_exceptions import run_jvm


@pytest.mark.parametrize("case", [
    "cookie_attributes_and_store_replacement",
    "restored_cookies_follow_native_request_constraints",
    "invalid_native_cookie_names_and_versions_are_catchable",
])
def test_native_cookie_state_on_jvm(case, tmp_path):
    result = run_jvm(f'''
from tests.java.test_android_cookies import test_{case}
def main() -> str:
    test_{case}()
    return "ok"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"
