import pytest

from pyjs.android.reorder import _SwapGuard
from tests.java.test_exceptions import run_jvm


@pytest.mark.parametrize("horizontal", [True, False], ids=["horizontal", "vertical"])
@pytest.mark.parametrize("direction", [-1, 1], ids=["negative", "positive"])
def test_swap_requires_a_deliberate_reversal_for_the_same_holder(horizontal, direction):
    guard = _SwapGuard()
    guard.slop = 8
    target, other = object(), object()
    x, y = (direction * 100, 0) if horizontal else (0, direction * 100)
    assert guard.allows(target, x, y)
    guard.record(target, 0, 0, x, y)
    for displacement, allowed in [(0, False), (40, False), (-7, False),
                                   (-8, True), (-40, True)]:
        next_x = x + displacement * direction if horizontal else x
        next_y = y if horizontal else y + displacement * direction
        assert guard.allows(target, next_x, next_y) is allowed
        assert guard.allows(other, next_x, next_y)
    guard.reset()
    assert guard.target is None
    assert guard.allows(target, x, y)


def test_captured_staggered_relayout_does_not_arm_a_second_swap():
    guard = _SwapGuard()
    guard.slop = 21
    target = object()
    guard.record(target, 552, 12, 0, -40)
    # The holder moved to adapter position 0 but remains in the right span.
    # Native selection proposes the same partner at successive pointer samples.
    for x, y in [(-10, -42), (-18, -43), (-22, -44)]:
        assert not guard.allows(target, x, y)
    assert guard.allows(target, 560, 12)
    guard.record(target, 12, 12, 560, 12)
    assert not guard.allows(target, 570, 12)
    assert guard.allows(target, 539, 12)


def test_other_target_and_zero_displacement_replace_the_previous_guard():
    guard = _SwapGuard()
    first, second = object(), object()
    guard.record(first, 0, 0, 10, 30)
    assert not guard.allows(first, 11, 31)
    guard.record(second, 10, 30, 80, 40)
    assert guard.allows(first, 81, 41)
    assert not guard.allows(second, 81, 41)
    guard.record(second, 80, 40, 80, 40)
    assert guard.allows(second, 80, 40)


def test_target_comparison_uses_identity_not_equality():
    class Equal:
        def __eq__(self, other):
            return True

    first, second = Equal(), Equal()
    guard = _SwapGuard()
    guard.record(first, 0, 0, 100, 0)
    assert not guard.allows(first, 101, 0)
    assert guard.allows(second, 101, 0)


def test_swap_guard_reference_identity_and_reversal_on_jvm(tmp_path):
    result = run_jvm('''
from pyjs.android.reorder import _SwapGuard

class Token:
    pass

def main() -> str:
    first = Token()
    second = Token()
    guard = _SwapGuard()
    guard.slop = 21
    guard.record(first, 552, 12, 0, -40)
    assert not guard.allows(first, -10, -42)
    assert guard.allows(second, -10, -42)
    assert guard.allows(first, 21, -42)
    guard.record(first, 12, 12, 560, 12)
    assert not guard.allows(first, 570, 12)
    assert guard.allows(first, 539, 12)
    guard.reset()
    assert guard.allows(first, 570, 12)
    return "identity and reversal"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "identity and reversal"
