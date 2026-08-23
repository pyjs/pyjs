from typing import cast

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import button, div, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
def CalendarDayButton(day: int, selected: bool = False, disabled: bool = False):
    attributes = {
        "aria-label": "Select day " + str(day),
        "aria-pressed": "true" if selected else "false",
        "data-day": str(day),
        "data-selected": "true" if selected else "false",
        "data-slot": "calendar-day",
        "type": "button",
    }
    if disabled:
        attributes["disabled"] = ""
    return button(
        tw(
            "inline-flex size-9 items-center justify-center rounded-md text-sm hover:bg-slate-100 "
            "data-[selected=true]:bg-slate-950 data-[selected=true]:text-white "
            "disabled:pointer-events-none disabled:opacity-40"
        ),
        attributes,
        str(day),
    )


@js
class Calendar(Widget):
    def __init__(
        self,
        month: str,
        year: int,
        *,
        days: int = 31,
        starts_on: int = 0,
        selected_day: int = 0,
        disabled_days: list[int] | None = None,
    ):
        super().__init__()
        if days < 28 or days > 31:
            raise ValueError("Calendar days must be between 28 and 31")
        if starts_on < 0 or starts_on > 6:
            raise ValueError("Calendar starts_on must be between 0 and 6")
        if disabled_days is None:
            disabled_days = []
        self.add(
            tw("w-fit rounded-lg border border-slate-200 bg-white p-3"),
            {
                "aria-label": month + " " + str(year),
                "data-selected-day": str(selected_day) if selected_day > 0 else "",
                "data-slot": "calendar",
            },
            div(
                tw("mb-3 text-center text-sm font-medium"),
                {"data-slot": "calendar-caption"},
                month + " " + str(year),
            ),
            div(
                tw("grid grid-cols-7 text-center text-xs text-slate-500"),
                {"aria-hidden": "true", "data-slot": "calendar-weekdays"},
                tag("span", "Su"),
                tag("span", "Mo"),
                tag("span", "Tu"),
                tag("span", "We"),
                tag("span", "Th"),
                tag("span", "Fr"),
                tag("span", "Sa"),
            ),
            self.build_grid(days, starts_on, selected_day, disabled_days),
        )
        self.addEventListener("click", self.day_clicked)

    def build_grid(
        self,
        days: int,
        starts_on: int,
        selected_day: int,
        disabled_days: list[int],
    ):
        grid = div(
            tw("mt-1 grid grid-cols-7"),
            {"data-slot": "calendar-grid", "role": "grid"},
        )
        for _blank in range(starts_on):
            grid.append(tag("span", {"aria-hidden": "true"}))
        for day in range(1, days + 1):
            grid.append(
                CalendarDayButton(
                    day,
                    selected=day == selected_day,
                    disabled=day in disabled_days,
                )
            )
        return grid

    def selected_day(self) -> str:
        value = self.getAttribute("data-selected-day")
        if value is None:
            return ""
        return value

    def select_day(self, day: str):
        buttons = self.querySelectorAll("[data-slot=calendar-day]")
        for day_button in buttons:
            selected = day_button.getAttribute("data-day") == day
            day_button.setAttribute("aria-pressed", "true" if selected else "false")
            day_button.setAttribute("data-selected", "true" if selected else "false")
        self.setAttribute("data-selected-day", day)

    def on_select(self, callback: callable):
        self.addEventListener("click", callback)

    def day_clicked(self, event: Event):
        target = cast(Element, event.target)
        day_button = target.closest("[data-slot=calendar-day]")
        if day_button is None:
            return
        value = day_button.getAttribute("data-day")
        if value is not None:
            self.select_day(value)
