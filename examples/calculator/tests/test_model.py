from pyjs import js

from ..model import Calculator


@js
def check_calculator(calculator: Calculator):
    calculator.press("digit", "1")
    calculator.press("digit", "2")
    calculator.press("decimal", ".")
    calculator.press("decimal", ".")
    calculator.press("digit", "5")
    assert calculator.display_value == "12.5"
    calculator.press("action", "sign")
    calculator.press("decimal", ".")
    assert calculator.value() == -12.5

    calculator.press("action", "clear")
    calculator.press("digit", "8")
    calculator.press("operator", "+")
    calculator.press("digit", "2")
    calculator.press("operator", "*")
    assert calculator.value() == 10.0
    calculator.press("operator", "-")
    calculator.press("digit", "3")
    calculator.press("equals", "=")
    assert calculator.value() == 7.0
    calculator.press("operator", "*")
    calculator.press("digit", "6")
    calculator.press("equals", "=")
    assert calculator.value() == 42.0
    calculator.press("operator", "/")
    calculator.press("digit", "2")
    calculator.press("equals", "=")
    assert calculator.value() == 21.0

    calculator.press("action", "percent")
    assert calculator.value() == 0.21
    calculator.press("decimal", ".")
    calculator.press("digit", "5")
    assert calculator.value() == 0.5

    calculator.press("operator", "/")
    calculator.press("digit", "0")
    calculator.press("equals", "=")
    assert calculator.display_value == "Error"
    assert calculator.error
    assert calculator.pending_operator == ""
    calculator.press("operator", "+")
    calculator.press("action", "sign")
    calculator.press("action", "percent")
    assert calculator.display_value == "Error"
    calculator.press("decimal", ".")
    calculator.press("digit", "5")
    assert calculator.value() == 0.5
    assert not calculator.error

    calculator.press("operator", "/")
    calculator.press("digit", "0")
    calculator.press("equals", "=")
    calculator.press("digit", "4")
    assert calculator.value() == 4.0
    assert not calculator.error
    calculator.press("action", "clear")
    assert calculator.display_value == "0"
    assert calculator.stored_value == 0.0
    assert calculator.replace_display


@js
def test_shared_calculator_model():
    check_calculator(Calculator())
