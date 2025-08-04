import sys
if "--qt" in sys.argv:
    from pyjs.qt import use_qt; use_qt()
from pyjs.ui import Widget
from pyjs.ui.button import Button
from pyjs.ui.card import (
    Card, CardHeader, CardTitle,
    CardContent, CardFooter
)
from pyjs.ui.text import Text


class CounterApp(Widget):
    def __init__(self):
        super().__init__()
        self.counter = Text('0')
        self.add_button = Button("+")
        self.add_button.on_click(self.increment)
        self.sub_button = Button("−")
        self.sub_button.on_click(self.decrement)
        self.add(
            Card(
                CardHeader(CardTitle("Counting App")),
                CardContent(self.counter),
                CardFooter(self.sub_button, self.add_button)
            )
        )

    def get_counter(self):
        return int(self.counter.get_content())

    def increment(self):
        self.counter.set_content(str(self.get_counter() + 1))

    def decrement(self):
        self.counter.set_content(str(self.get_counter() - 1))


def main():
    return CounterApp()


if __name__ == "__main__":
    if "--qt" in sys.argv:
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication(sys.argv)
        window = QWidget()
        window.setWindowTitle("Counter App")
        window.setLayout(CounterApp())
        window.setMinimumSize(300, 200)
        window.show()
        sys.exit(app.exec())
    else:
        from pathlib import Path
        from pyjs.server import serve
        serve(Path(__file__).stem, "", main.__name__)
