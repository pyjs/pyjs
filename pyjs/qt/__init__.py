import sys
import pkgutil
import importlib
from PySide6.QtWidgets import QVBoxLayout


def use_qt():
    sys.modules["pyjs.ui"] = sys.modules[__name__]
    for _, name, ispkg in pkgutil.iter_modules(__path__):
        sys.modules[f"pyjs.ui.{name}"] = importlib.import_module(f"pyjs.qt.{name}")


class Widget(QVBoxLayout):

    def add(self, *children):
        for child in children:
            if isinstance(child, Widget):
                self.addLayout(child)
            else:
                self.addWidget(child)
