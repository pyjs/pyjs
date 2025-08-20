from pyjs import js
from pyjs.domx import ProxyElement, button, tw


@js
class Button(ProxyElement):
    def __init__(self, text: str):
        self.element = button(
            "button",
            tw("px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg"),
            text
        )

    def on_click(self, cb: callable):
        self.element.addEventListener("click", cb)
