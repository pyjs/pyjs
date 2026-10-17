"""Shared source cases for ownership metadata and persistent native execution."""

PERSISTENT_ALIAS_DEFINITIONS = '''
from dataclasses import dataclass, field
from collections.abc import Callable
class Box:
    def __init__(self, number: int):
        self.number = number
SHARED: list[Box] = []
LABEL: str = "label"
KINDS: tuple[str, ...] = ("a", "b")
MUTABLE: tuple[list[Box], ...] = ([],)
class Holder:
    def __init__(self, items: list[Box]):
        self.items = items
        self.label = ""
    def replace(self) -> None:
        self.items = SHARED
@dataclass
class Bag:
    items: list[Box] = field(default_factory=list)
    def __post_init__(self) -> None:
        if not self.items:
            self.items = SHARED
def shared_items() -> list[Box]:
    return SHARED
def shared_holder() -> Holder:
    return Holder(SHARED)
def put(target: list[Box], value: Box) -> None:
    target.append(value)
def keep_args(*args: Box) -> tuple[Box, ...]:
    return args
def call(getter: Callable[[], list[Box]]) -> list[Box]:
    return getter()
class Tagged:
    def __init__(self):
        self.label = LABEL
        self.kinds = KINDS
        self.children: list[Box] = []
class TextWriter:
    def __init__(self, item: Box):
        self.item = item
    def __str__(self) -> str:
        SHARED.append(self.item)
        return "stored"
'''

# Bodies are used verbatim in both tests. The final boolean describes whether
# the Box must outlive the invocation, not whether the receiver itself escapes.
PERSISTENT_ALIAS_CASES = [
    ("postinit", "holder = Bag()\nholder.items.append(Box(number))", True),
    ("explicit-postinit", "holder = Bag([])\nholder.items.append(Box(number))", True),
    ("constructor", "holder = Holder(SHARED)\nholder.items.append(Box(number))", True),
    ("field-write", "holder = Holder([])\nholder.items = SHARED\nholder.items.append(Box(number))", True),
    ("method-write", "holder = Holder([])\nholder.replace()\nholder.items.append(Box(number))", True),
    ("returned-storage", "holder = Holder(shared_items())\nholder.items.append(Box(number))", True),
    ("returned-holder", "holder = shared_holder()\nholder.items.append(Box(number))", True),
    ("unknown-pack", "pair = (SHARED, Box(number))\nput(*pair)", True),
    ("nested-pack", "put(*(*(SHARED,), Box(number)))", True),
    ("varargs", "SHARED.append(keep_args(Box(number), Box(number + 10))[1])", True),
    ("starred-varargs", "SHARED.append(keep_args(*(Box(number), Box(number + 10)))[1])", True),
    ("function-value", "getter = shared_items\nholder = Holder(getter())\nholder.items.append(Box(number))", True),
    ("lambda-value", "getter: Callable[[], list[Box]] = lambda: SHARED\nholder = Holder(getter())\nholder.items.append(Box(number))", True),
    ("callback-parameter", "holder = Holder(call(shared_items))\nholder.items.append(Box(number))", True),
    ("mutable-tuple", "holder = Holder(MUTABLE[0])\nholder.items.append(Box(number))", True),
    ("constant-field", "holder = Tagged()\nholder.children.append(Box(number))", False),
    ("constant-local-tuple", "holder = Holder([])\npair = (LABEL, holder)\npair[1].items.append(Box(number))", False),
    ("converted-label", "holder = Holder([])\nholder.label = str(number)\nholder.items.append(Box(number))", False),
    ("converted-mutable-tuple", "values = tuple([SHARED])\nvalues[0].append(Box(number))", True),
    ("conversion-effect", "str(TextWriter(Box(number)))", True),
    ("local-holder", "holder = Holder([])\nholder.items.append(Box(number))", False),
    ("local-varargs", "local = keep_args(Box(number), Box(number + 10))\nnumber = local[0].number", False),
]
