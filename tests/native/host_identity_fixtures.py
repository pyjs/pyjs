"""Real host records for nominal, headed copy-in tests."""

from pyjs import float32, int8


class Record:
    __slots__ = ("text", "items")
    text: str
    items: list[str]

    def __init__(self, text: str):
        self.text = text
        self.items: list[str] = [text]

    def label(self) -> str:
        return "base:" + self.text


class SpecialRecord(Record):
    __slots__ = ()

    def label(self) -> str:
        return "child:" + self.text


class Empty:
    __slots__ = ()

    def __init__(self):
        pass


class PackedRecord:
    def __init__(self, text: str):
        self.tiny = int8(-3)
        self.number = float32(1.25)
        self.ready = True
        self.text = text
