from pyjs.android import OnClickListener, TextView, View
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
from pyjs.java import current_time_millis, i32
from pyjs.java.time import instant_from_epoch_millis, local_date_time, system_zone


class DateTimePreview(OnClickListener):
    def __init__(self, output: TextView):
        self.output = output
        self.dialog: AlertDialog | None = None

    def onClick(self, view: View) -> None:
        self.close()
        local = instant_from_epoch_millis(current_time_millis() + 3_600_000).atZone(
            system_zone()).toLocalDateTime()
        dialog = DatePickerDialog(view.getContext(), PreviewDate(self, local.getHour(), local.getMinute()),
                                  local.getYear(), i32(local.getMonthValue() - 1), local.getDayOfMonth())
        self.open(dialog)

    def open(self, dialog: AlertDialog) -> None:
        self.dialog = dialog
        dialog.setOnCancelListener(PreviewCancelled(self))
        dialog.show()

    def close(self) -> None:
        if self.dialog is not None:
            self.dialog.dismiss()
            self.dialog = None


class PreviewCancelled(DialogCancelListener):
    def __init__(self, preview: DateTimePreview):
        self.preview = preview

    def onCancel(self, dialog: DialogInterface) -> None:
        self.preview.dialog = None
        self.preview.output.setText("Selection cancelled · no reminder scheduled")


class PreviewDate(DateSetListener):
    def __init__(self, preview: DateTimePreview, hour: i32, minute: i32):
        self.preview = preview
        self.hour = hour
        self.minute = minute

    def onDateSet(self, view: DatePicker, year: i32, month: i32, day: i32) -> None:
        context = self.preview.output.getContext()
        self.preview.open(TimePickerDialog(context, PreviewTime(self.preview, year, month, day),
                                           self.hour, self.minute, is_24_hour_format(context)))


class PreviewTime(TimeSetListener):
    def __init__(self, preview: DateTimePreview, year: i32, month: i32, day: i32):
        self.preview = preview
        self.year = year
        self.month = month
        self.day = day

    def onTimeSet(self, view: TimePicker, hour: i32, minute: i32) -> None:
        self.preview.dialog = None
        local = local_date_time(self.year, i32(self.month + 1), self.day, hour, minute)
        zone = system_zone()
        resolved = local.atZone(zone)
        if resolved.toLocalDateTime().toString() != local.toString():
            self.preview.output.setText("That time does not exist here. Choose another time.")
        else:
            self.preview.output.setText(local.toString().replace("T", " ") + " " + zone.getId()
                                        + "\nPreview only · no reminder scheduled")
