import pytest

from pyjs import js
from pyjs.testing.web import mount
from pyjs.web.domx import div

pytestmark = pytest.mark.pyjs_web


@js
def test_numeric_formatting_renders_expected_dom_text():
    value = 1.234
    count = 42
    ratio = 0.256
    output = div(f"{value:.2f}|{count:05d}|{ratio:.1%}|{2.0}")

    mount(output)

    assert output.textContent == "1.23|00042|25.6%|2.0"
