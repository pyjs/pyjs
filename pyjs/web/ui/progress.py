from pyjs import js
from pyjs.web.domx import ref, tag, tw
from pyjs.web.ui import Widget


@js
class ProgressBar(Widget):
    def __init__(self, value: int = 0, label: str = "Progress"):
        super().__init__()
        self.indicator = ref(
            tag(
                "div",
                tw("h-full bg-slate-950 transition-all"),
                {"data-slot": "progress-indicator"},
            )
        )
        self.add(
            tw("relative h-2 w-full overflow-hidden rounded-full bg-slate-200"),
            {
                "aria-label": label,
                "aria-valuemax": "100",
                "aria-valuemin": "0",
                "data-slot": "progress",
                "role": "progressbar",
            },
            self.indicator,
        )
        self.set_value(value)

    def set_value(self, value: int):
        if value < 0:
            value = 0
        elif value > 100:
            value = 100
        value_text = str(value)
        self.setAttribute("aria-valuenow", value_text)
        self.setAttribute("value", value_text)
        self.indicator.setAttribute("style", "width: " + value_text + "%")

    def current_value(self) -> int:
        value = self.getAttribute("value")
        if value is None:
            return 0
        return int(value)
