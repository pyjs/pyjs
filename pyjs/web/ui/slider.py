from typing import cast

from pyjs import js
from pyjs.web.domx import ProxyElement, input, tw
from pyjs.web.html import HTMLInputElement


@js
class Slider(ProxyElement):
    def __init__(
        self,
        value: int = 0,
        minimum: int = 0,
        maximum: int = 100,
        step: int = 1,
        label: str = "",
        name: str = "",
    ):
        if maximum <= minimum:
            raise ValueError("Slider maximum must be greater than minimum")
        if value < minimum:
            value = minimum
        if value > maximum:
            value = maximum
        self.element = input(
            tw(
                "h-5 w-full cursor-pointer accent-slate-950 "
                "disabled:cursor-not-allowed disabled:opacity-50"
            ),
            {
                "aria-label": label,
                "data-slot": "slider",
                "max": str(maximum),
                "min": str(minimum),
                "name": name,
                "step": str(step),
                "type": "range",
                "value": str(value),
            },
        )

    def get_value(self) -> str:
        return cast(HTMLInputElement, self.element).value

    def set_value(self, value: int):
        cast(HTMLInputElement, self.element).value = str(value)

    def on_input(self, callback: callable):
        self.element.addEventListener("input", callback)
