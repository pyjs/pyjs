from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
from pyjs.qt import Widget
from pyjs.qt.text import Text
from pyjs.qt.button import Button


class Card(Widget, QVBoxLayout):
    def __init__(self, *children):
        super().__init__()
        self.add(*children)


class CardHeader(Widget, QHBoxLayout):
    def __init__(self, *children):
        super().__init__()
        self.add(*children)


class CardTitle(Text):
    pass


class CardDescription(Text):
    pass


class CardAction(Button):
    pass


class CardContent(Widget, QVBoxLayout):
    def __init__(self, *children):
        super().__init__()
        self.add(*children)


class CardFooter(Widget, QHBoxLayout):
    def __init__(self, *children):
        super().__init__()
        self.add(*children)
