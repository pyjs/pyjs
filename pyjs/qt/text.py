from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class Text(QLabel):

    def __init__(self, text):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("font-size: 48px;")

    def get_content(self):
        return self.text()

    def set_content(self, text):
        self.setText(text)
        return text