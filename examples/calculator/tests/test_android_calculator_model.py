import pytest
from pyjs_examples.calculator.android import AndroidCalculator

pytestmark = pytest.mark.pyjs_python


def test_android_calculator_uses_the_same_arithmetic_behavior():
    calculator = AndroidCalculator()

    calculator.input_digit("1")
    calculator.input_digit("2")
    calculator.choose_operator("+")
    calculator.input_digit("7")

    assert calculator.calculate() == 19.0
    assert calculator.display.text == "19.0"


def test_android_calculator_builds_a_complete_native_keypad():
    calculator = AndroidCalculator()
    page = calculator.page()

    assert page.content.getViewById("calculator-display") is calculator.display
    assert page.content.getViewById("key-clear") is not None
    assert page.content.getViewById("key-+") is not None
    assert page.content.getViewById("key-=") is not None
