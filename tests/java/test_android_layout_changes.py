import pytest

from pyjs.android import OnLayoutChangeListener, View
from pyjs.android.testing import application_context, run_on_main
from pyjs.java import i32
from pyjs.java.concurrent import Runnable

pytestmark = pytest.mark.pyjs_android_jvm


class BoundsObserver(OnLayoutChangeListener):
    def __init__(self) -> None:
        self.calls = 0
        self.bounds: list[int] = []
        self.previous: list[int] = []
        self.view: View | None = None

    def onLayoutChange(
        self, view: View, left: i32, top: i32, right: i32, bottom: i32,
        old_left: i32, old_top: i32, old_right: i32, old_bottom: i32,
    ) -> None:
        self.calls += 1
        self.bounds = [int(left), int(top), int(right), int(bottom)]
        self.previous = [int(old_left), int(old_top), int(old_right), int(old_bottom)]
        self.view = view
        assert view.getWidth() == right - left
        assert view.getHeight() == bottom - top


class LayoutChanges(Runnable):
    def run(self) -> None:
        view = View(application_context())
        first = BoundsObserver()
        second = BoundsObserver()
        view.addOnLayoutChangeListener(first)
        view.addOnLayoutChangeListener(first)
        view.addOnLayoutChangeListener(second)
        view.layout(10, 20, 210, 120)
        assert first.calls == 1 and second.calls == 1
        assert first.view is view and second.view is view
        assert first.bounds == [10, 20, 210, 120]
        assert first.previous == [0, 0, 0, 0]

        view.layout(10, 20, 210, 120)
        assert first.calls == 1 and second.calls == 1
        view.layout(-5, 30, 395, 180)
        assert first.calls == 2 and second.calls == 2
        assert first.bounds == [-5, 30, 395, 180]
        assert first.previous == [10, 20, 210, 120]

        view.removeOnLayoutChangeListener(first)
        view.removeOnLayoutChangeListener(first)
        view.layout(0, 0, 100, 50)
        assert first.calls == 2 and second.calls == 3
        assert second.previous == [-5, 30, 395, 180]
        view.addOnLayoutChangeListener(first)
        view.layout(0, 0, 100, 80)
        assert first.calls == 3 and second.calls == 4
        assert first.previous == [0, 0, 100, 50]
        assert first.bounds == [0, 0, 100, 80]
        view.removeOnLayoutChangeListener(first)
        view.removeOnLayoutChangeListener(second)
        view.layout(0, 0, 0, 0)
        assert first.calls == 3 and second.calls == 4


def test_native_layout_observers_receive_bounds_and_can_be_removed() -> None:
    run_on_main(LayoutChanges())
