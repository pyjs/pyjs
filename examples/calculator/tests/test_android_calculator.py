import pytest
from pyjs.android.testing import background, by_id, by_text, launch, recreate, resume

from ..android import CalculatorActivity
from ..model import Calculator
from .test_model import check_calculator

pytestmark = pytest.mark.pyjs_android_jvm


def test_calculator_runs_on_android() -> None:
    launch(CalculatorActivity)
    for index in range(19):
        by_id(100 + index).scroll_to()
        by_id(100 + index).assert_displayed()
    by_text("7").scroll_to()
    by_text("7").click()
    by_text("+").scroll_to()
    by_text("+").click()
    by_text("8").scroll_to()
    by_text("8").click()
    by_text("=").scroll_to()
    by_text("=").click()
    by_text("15.0").scroll_to()
    by_text("15.0").assert_displayed()


def test_shared_model_on_android() -> None:
    check_calculator(Calculator())


def test_decimal_after_sign_change_on_android() -> None:
    launch(CalculatorActivity)
    for label in ["5", "±", ".", "+", "2", "="]:
        by_text(label).scroll_to()
        by_text(label).click()
    by_text("-3.0").scroll_to()
    by_text("-3.0").assert_displayed()


def test_pending_calculation_survives_recreation() -> None:
    launch(CalculatorActivity)
    for label in ["7", "+"]:
        by_text(label).scroll_to()
        by_text(label).click()
    background()
    resume()
    recreate()
    for label in ["8", "="]:
        by_text(label).scroll_to()
        by_text(label).click()
    by_text("15.0").scroll_to()
    by_text("15.0").assert_displayed()
