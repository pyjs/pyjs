import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("left, right, expression, invocation", [
    ("Left", "Right", "(left == right, left != right)", "check(Left(), Right())"),
    ("Left", "Right | Other", "(left == right, left != right)",
     "check(Left(), Right()) + check(Left(), Other())"),
    ("tuple[Left | Right, ...]", "tuple[Left | Right, ...]", "(left == right, left != right)",
     "check(pair(Left()), pair(Right()))"),
    ("Left", "Right", "left < right", "check(Left(), Right())"),
], ids=["static", "union", "tuple", "ordering"])
def test_structural_interfaces_do_not_reverse_rich_comparisons(tmp_path, optimize, left, right, expression, invocation):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
LOG: list[str] = []
class Left:
    __pyjs_structural__ = True
    def __eq__(self, other: object) -> bool:
        LOG.append("Left.eq")
        gc_collect()
        return False
    def __lt__(self, other: "Right") -> bool:
        LOG.append("Left.lt")
        gc_collect()
        return False
class Right:
    def __eq__(self, other: object) -> bool:
        LOG.append("Right.eq")
        gc_collect()
        return True
    def __gt__(self, other: Left) -> bool:
        LOG.append("Right.gt")
        return True
class Other:
    pass
def pair(value: Left | Right) -> tuple[Left | Right, ...]:
    return (value,)
def check(left: {left}, right: {right}) -> str:
    LOG.clear()
    result = {expression}
    return repr(result) + repr(LOG)
def main() -> str:
    gc_set_threshold(1)
    return {invocation}
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_priority_preserves_storage_and_one_sided_virtual_dispatch(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Operand[T]:
    def __init__(self, value: T):
        self.value = value
    def __add__(self, other: object) -> str:
        gc_collect()
        return "forward"
    def __radd__(self, other: object) -> str:
        return "reverse"
    def __eq__(self, other: object) -> bool:
        gc_collect()
        return False
    def __lt__(self, other: object) -> bool:
        return False
    def __gt__(self, other: object) -> bool:
        return False
class Child(Operand[int]):
    def __radd__(self, other: object) -> str:
        gc_collect()
        return "child"
    def __eq__(self, other: object) -> bool:
        gc_collect()
        return True
    def __gt__(self, other: object) -> bool:
        return True
def check(left: Operand[str], right: Operand[int]) -> str:
    return repr((left + right, left == right, left < right))
def main() -> str:
    gc_set_threshold(1)
    text = Operand("text")
    ordinary = Operand(1)
    child = Child(2)
    return repr((text + child, text == child, text < child,
                 check(text, ordinary), check(text, child)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
