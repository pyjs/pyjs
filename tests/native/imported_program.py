from datetime import timedelta

IMPORTED_LABEL = "answer"
IMPORTED_OFFSET = 40

# Reached constants must not pull unrelated module values into native code.
UNUSED_DURATIONS = {"hour": timedelta(hours=1)}


def _calculate_imported_constant() -> int:
    return 41


CALCULATED_OFFSET = _calculate_imported_constant()


class Counter:
    def __init__(self, value: int):
        self.value = value

    def increment(self) -> int:
        return self.value + 1


def calculate(value: int) -> int:
    return Counter(value).increment()


def main(value: int) -> int:
    return value + 4
