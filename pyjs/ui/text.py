from pyjs import js
from pyjs.domx import ProxyElement, span


@js
class Text(ProxyElement):
    def __init__(self, text: str):
        self.element = span(text)

    def get_content(self) -> str:
        return self.element.textContent.strip()

    def set_content(self, text: str) -> str:
        self.element.textContent = text
        return text
