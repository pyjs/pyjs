import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    GENERIC_OPERATOR_CONTRACT,
    STRUCTURAL_OPERATOR_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [STRUCTURAL_OPERATOR_CONTRACT, GENERIC_OPERATOR_CONTRACT], ids=["structural", "generic"])
def test_typing_compatibility_does_not_change_operator_priority(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                          optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_specialization_does_not_reverse_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
class Box:
    def __init__(self, value: int):
        self.value = value
    def __eq__(self, other: "Box") -> bool:
        return self.value < other.value
def main() -> str:
    fixed = (Box(2), Box(2))
    view: tuple[Box, ...] = (Box(1), Box(1))
    return repr((fixed == view, view == fixed, fixed != view, view != fixed))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_union_equality_preserves_callback_order_errors_and_roots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Box:
    def __init__(self, value: int, events: list[int]):
        self.value = value
        self.events = events
    def __eq__(self, other: object) -> bool:
        self.events.append(self.value)
        gc_collect()
        if self.value < 0:
            raise ValueError("stop")
        if isinstance(other, Box):
            return self.value == other.value
        return False
class First:
    def __init__(self, value: int, events: list[int]):
        self.item = Box(value, events)
class Second:
    def __init__(self):
        self.item = "second"
def check(a: First | Second, b: First | Second, events: list[int]) -> str:
    fixed = (a.item, a.item)
    view: tuple[str | Box, ...] = (b.item, b.item)
    rows: list[bool] = []
    try:
        rows.append(fixed == view)
        rows.append(view == fixed)
        rows.append(fixed != view)
        rows.append(view != fixed)
    except ValueError:
        events.append(99)
    return repr(rows) + repr(events)
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    rows: list[str] = []
    for value in (1, 2, -1):
        events.clear()
        rows.append(check(First(value, events), First(1, events), events))
    events.clear()
    rows.append(check(First(1, events), Second(), events))
    events.clear()
    rows.append(check(Second(), Second(), events))
    return repr(rows)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
