"""Isolated comparisons must reach their own bodies, not incidental callers."""

COMPARISON_PAIRS = (
    ("==", "__eq__", "__eq__"),
    ("!=", "__ne__", "__ne__"),
    ("<", "__lt__", "__gt__"),
    ("<=", "__le__", "__ge__"),
    (">", "__gt__", "__lt__"),
    (">=", "__ge__", "__le__"),
)


def declining_pair(operator, forward, reflected, result="bool | NotImplementedType"):
    return f'''
from types import NotImplementedType
class Left:
    def {forward}(self, other: object) -> {result}:
        return NotImplemented
    def unused(self) -> int:
        return 99
class Right:
    def {reflected}(self, other: object) -> bool:
        return True
    def unused(self) -> int:
        return 100
def main() -> str:
    return str(Left() {operator} Right())
'''
