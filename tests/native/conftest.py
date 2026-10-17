import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SSR_PERFORMANCE_TEST = PROJECT_ROOT / "tests/django/test_ssr_performance.py"


@pytest.fixture(scope="session")
def settings_html():
    spec = importlib.util.spec_from_file_location(
        "pyjs_native_ssr_workload",
        SSR_PERFORMANCE_TEST,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._render_pyjs_settings()
