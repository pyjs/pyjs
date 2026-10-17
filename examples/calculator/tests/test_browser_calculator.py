import pytest
from pyjs import js
from pyjs.testing.web import mount
from pyjs.web.dom import Element
from pyjs.web.events import Event

from ..calculator import CalculatorApp
from ..model import Calculator
from .test_model import check_calculator

pytestmark = pytest.mark.pyjs_web


@js
def click(button: Element):
    button.dispatchEvent(Event("click"))


@js
def mounted_calculator() -> CalculatorApp:
    app = CalculatorApp()
    mount(app)
    return app


@js
def test_calculator_renders_a_complete_keypad():
    app = mounted_calculator()

    assert len(app.querySelectorAll("[data-key]")) == 19
    assert app.display.textContent.strip() == "0"


@js
def test_calculator_buttons_complete_an_expression():
    app = mounted_calculator()
    click(app.one_button.element)
    click(app.two_button.element)
    click(app.add_button.element)
    click(app.seven_button.element)
    click(app.equals_button.element)

    assert float(app.display.textContent.strip()) == 19.0


@js
def test_calculator_supports_decimal_sign_percent_and_clear():
    app = mounted_calculator()
    click(app.five_button.element)
    click(app.zero_button.element)
    click(app.percent_button.element)
    assert float(app.display.textContent.strip()) == 0.5

    click(app.sign_button.element)
    assert float(app.display.textContent.strip()) == -0.5

    click(app.clear_button.element)
    assert app.display.textContent.strip() == "0"


@js
def test_calculator_visual_showcase():
    app = mounted_calculator()
    click(app.one_button.element)
    click(app.two_button.element)
    click(app.multiply_button.element)
    click(app.three_button.element)
    click(app.equals_button.element)

    assert float(app.display.textContent.strip()) == 36.0


@js
def test_shared_model_in_browser():
    check_calculator(Calculator())


@js
def test_decimal_after_sign_change_remains_valid():
    app = mounted_calculator()
    click(app.five_button.element)
    click(app.sign_button.element)
    click(app.decimal_button.element)
    click(app.add_button.element)
    click(app.two_button.element)
    click(app.equals_button.element)
    assert float(app.display.textContent.strip()) == -3.0
    assert not app.error
