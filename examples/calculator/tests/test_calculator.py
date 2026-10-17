from pyjs import js

from ..calculator import CalculatorApp


@js
def test_enters_whole_and_decimal_numbers():
    calculator = CalculatorApp()
    calculator.input_digit("1")
    calculator.input_digit("2")
    calculator.input_decimal()
    calculator.input_digit("5")

    assert calculator.value() == 12.5


@js
def test_performs_the_four_arithmetic_operations():
    calculator = CalculatorApp()
    calculator.input_digit("8")
    calculator.choose_operator("+")
    calculator.input_digit("2")
    assert calculator.calculate() == 10.0

    calculator.choose_operator("-")
    calculator.input_digit("3")
    assert calculator.calculate() == 7.0

    calculator.choose_operator("*")
    calculator.input_digit("6")
    assert calculator.calculate() == 42.0

    calculator.choose_operator("/")
    calculator.input_digit("2")
    assert calculator.calculate() == 21.0


@js
def test_supports_sign_percent_clear_and_divide_by_zero():
    calculator = CalculatorApp()
    calculator.input_digit("5")
    calculator.input_digit("0")
    calculator.percent()
    assert calculator.value() == 0.5

    calculator.toggle_sign()
    assert calculator.value() == -0.5

    calculator.clear()
    assert calculator.value() == 0.0

    calculator.input_digit("9")
    calculator.choose_operator("/")
    calculator.input_digit("0")
    calculator.calculate()
    assert calculator.display_value == "Error"
    assert calculator.error


@js
def test_initial_and_calculation_state_is_stored_on_the_custom_element():
    calculator = CalculatorApp(initial_value="12.0")

    assert calculator.getAttribute("display-value") == "12.0"
    calculator.choose_operator("+")
    calculator.input_digit("3")

    stored_value = calculator.getAttribute("stored-value")
    assert stored_value is not None
    assert float(stored_value) == 12.0
    assert calculator.getAttribute("pending-operator") == "+"
    assert not calculator.hasAttribute("replace-display")
    assert not calculator.hasAttribute("error")
