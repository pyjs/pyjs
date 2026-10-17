import pytest
from pyjs.android import Context

from ..android import AndroidCalculator

pytestmark = pytest.mark.pyjs_python


def test_android_calculator_keeps_python_model_behavior():
    calculator = AndroidCalculator(Context())

    calculator.press("digit", "1")
    calculator.press("digit", "2")
    calculator.press("operator", "+")
    calculator.press("digit", "7")

    calculator.press("equals", "=")
    assert calculator.calculator.value() == 19.0
    assert calculator.display.text == "19.0"


def test_android_calculator_wires_key_events_to_the_model():
    calculator = AndroidCalculator(Context())
    seven = calculator.key("7", "7", "digit")
    seven.listener.onClick(seven)
    assert calculator.display.text == "7"
