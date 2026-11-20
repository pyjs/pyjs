import pytest

from pyjs.android import TextView, View
from pyjs.android.dialogs import AlertDialog, DialogCancelListener, DialogInterface
from pyjs.android.pickers import (
    DatePicker,
    DatePickerDialog,
    DateSetListener,
    TimePicker,
    TimePickerDialog,
    TimeSetListener,
    is_24_hour_format,
)
from pyjs.android.testing import (
    NoMatchingViewException,
    ViewAssertion,
    by_id,
    launch,
    press_back,
)
from pyjs.java import i32

from .android_robolectric_app import GreetingActivity

pytestmark = pytest.mark.pyjs_android_jvm


class DateResult(DateSetListener):
    def __init__(self, output: TextView):
        self.output = output

    def onDateSet(self, view: DatePicker, year: i32, month: i32, day: i32) -> None:
        assert view.getYear() == year and view.getMonth() == month and view.getDayOfMonth() == day
        self.output.setText(str(year) + ":" + str(month) + ":" + str(day))


class TimeResult(TimeSetListener):
    def __init__(self, output: TextView):
        self.output = output

    def onTimeSet(self, view: TimePicker, hour: i32, minute: i32) -> None:
        assert view.getHour() == hour and view.getMinute() == minute
        view.setHour(i32(0))
        view.setMinute(i32(1))
        assert view.getHour() == 0 and view.getMinute() == 1
        self.output.setText(str(hour) + ":" + str(minute))


class PickerCancelled(DialogCancelListener):
    def __init__(self, output: TextView):
        self.output = output

    def onCancel(self, dialog: DialogInterface) -> None:
        self.output.setText("Cancelled")


class OpenPicker(ViewAssertion):
    def __init__(self, date: bool, cancel: bool = False):
        self.date = date
        self.cancel = cancel

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and isinstance(view, TextView)
        context = view.getContext()
        dialog: AlertDialog
        if self.date:
            date_dialog = DatePickerDialog(context, DateResult(view), i32(2024), i32(0), i32(1))
            picker = date_dialog.getDatePicker()
            picker.setMinDate(1_704_067_200_000)
            picker.setMaxDate(1_735_689_600_000)
            picker.updateDate(i32(2024), i32(1), i32(28))
            date_dialog.updateDate(i32(2024), i32(1), i32(29))
            assert picker.getMonth() == 1 and picker.getDayOfMonth() == 29
            dialog = date_dialog
        else:
            is_24_hour_format(context)
            dialog = TimePickerDialog(context, TimeResult(view), i32(1), i32(0), True)
            dialog.updateTime(i32(23), i32(59))
        dialog.setOnCancelListener(PickerCancelled(view))
        assert not dialog.isShowing()
        dialog.show()
        assert dialog.isShowing() and dialog.getButton(i32(-1)) is not None
        if self.cancel:
            dialog.cancel()


def test_date_dialog_confirms_updated_leap_day_and_zero_based_month() -> None:
    launch(GreetingActivity)
    by_id(1001).check(OpenPicker(True))
    by_id(16908313).in_dialog().click()
    by_id(1001).assert_text("2024:1:29")


def test_time_dialog_confirms_updated_24_hour_time() -> None:
    launch(GreetingActivity)
    by_id(1001).check(OpenPicker(False))
    by_id(16908313).in_dialog().click()
    by_id(1001).assert_text("23:59")


def test_cancellation_does_not_commit_a_date_or_time() -> None:
    launch(GreetingActivity)
    by_id(1001).check(OpenPicker(True))
    press_back()
    by_id(1001).assert_text("Cancelled")
    by_id(1001).check(OpenPicker(False, True))
    by_id(1001).assert_text("Cancelled")
