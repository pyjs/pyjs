from pyjs import js
from pyjs.web.events import Event
from pyjs.web.ui.calendar import Calendar
from pyjs.web.ui.popover import Popover, PopoverContent, PopoverTrigger


@js
class DatePicker(Popover):
    def __init__(self, calendar: Calendar, placeholder: str = "Pick a date"):
        self.calendar = calendar
        self.trigger = PopoverTrigger(placeholder)
        super().__init__(self.trigger, PopoverContent(calendar))
        self.calendar.on_select(self.day_selected)
        self.setAttribute("data-slot", "date-picker")

    def selected_day(self) -> str:
        return self.calendar.selected_day()

    def day_selected(self, event: Event):
        selected_day = self.calendar.selected_day()
        if selected_day == "":
            return
        self.trigger.element.textContent = selected_day
        super().close()
