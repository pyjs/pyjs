from PySide6.QtWidgets import QPushButton


class Button(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setStyleSheet("font-size: 24px; padding: 10px;")

    def on_click(self, cb: callable):
        self.clicked.connect(cb)
