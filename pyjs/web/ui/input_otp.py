from pyjs import js
from pyjs.web.domx import div, input, span, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
def InputOTPSeparator():
    return div(
        tw("flex items-center text-slate-400"),
        {"aria-hidden": "true", "data-slot": "input-otp-separator"},
        "−",
    )


@js
class InputOTP(Widget):
    def __init__(self, length: int = 6, name: str = "", label: str = "One-time password"):
        super().__init__()
        if length < 1:
            raise ValueError("InputOTP length must be positive")
        self.length = length
        self.input = input(
            tw("absolute inset-0 z-10 h-full w-full opacity-0"),
            {
                "aria-label": label,
                "autocomplete": "one-time-code",
                "data-slot": "input-otp-input",
                "inputmode": "numeric",
                "maxlength": str(length),
                "name": name,
                "pattern": "[0-9]*",
                "type": "text",
            },
        )
        slots = div(
            tw("flex items-center"),
            {"aria-hidden": "true", "data-slot": "input-otp-group"},
        )
        for index in range(length):
            slots.append(
                span(
                    tw(
                        "relative flex size-10 items-center justify-center border-y border-r "
                        "border-slate-300 text-sm first:rounded-l-md first:border-l "
                        "last:rounded-r-md"
                    ),
                    {"data-index": str(index), "data-slot": "input-otp-slot"},
                )
            )
        self.add(
            tw("relative inline-flex"),
            {"data-slot": "input-otp"},
            self.input,
            slots,
        )
        self.input.addEventListener("input", self.update_slots)

    def get_value(self) -> str:
        return self.input.value

    def set_value(self, value: str):
        self.input.value = value.substring(0, self.length)
        self.render_value()

    def update_slots(self, event: Event):
        self.input.value = self.input.value.substring(0, self.length)
        self.render_value()

    def render_value(self):
        slots = self.querySelectorAll("[data-slot=input-otp-slot]")
        for index in range(len(slots)):
            if index < len(self.input.value):
                slots[index].textContent = self.input.value[index]
            else:
                slots[index].textContent = ""
