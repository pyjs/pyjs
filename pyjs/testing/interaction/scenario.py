from pyjs import js
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderDecision,
    ReorderItem,
    ReorderRow,
    ReorderSession,
)

from .gesture import GestureScript
from .reorder import replay_reorder_gesture


@js
class ReorderScenario:
    """One readable reorder contract shared by pure and platform tests."""

    def __init__(
        self,
        name: str,
        items: list[ReorderItem],
        source_index: int,
        rows: list[ReorderRow],
        gesture: GestureScript,
        expected_order: list[str],
        expected_depths: list[int],
        max_depth: int = 5,
        indent_step: float = 36,
    ):
        self.name = name
        self.items = items
        self.source_index = source_index
        self.rows = rows
        self.gesture = gesture
        self.expected_order = expected_order
        self.expected_depths = expected_depths
        self.max_depth = max_depth
        self.indent_step = indent_step

    def begin(self) -> ReorderSession:
        session = HierarchicalReorder(self.max_depth, self.indent_step).begin(
            self.items,
            self.source_index,
        )
        if not isinstance(session, ReorderSession):
            raise AssertionError(self.name + ": source index was invalid")
        return session

    def replay(self) -> ReorderDecision:
        decisions = replay_reorder_gesture(
            self.begin(),
            self.rows,
            self.gesture,
        )
        if len(decisions) == 0:
            raise AssertionError(self.name + ": gesture produced no preview")
        return decisions[-1]

    def assert_decision(self, decision: ReorderDecision | None) -> None:
        if not isinstance(decision, ReorderDecision):
            raise AssertionError(self.name + ": platform produced no decision")
        actual_order = decision.committed_item_ids()
        if actual_order != self.expected_order:
            raise AssertionError(
                self.name
                + ": expected order "
                + repr(self.expected_order)
                + ", got "
                + repr(actual_order)
            )
        actual_depths = decision.committed_depths()
        if actual_depths != self.expected_depths:
            raise AssertionError(
                self.name
                + ": expected depths "
                + repr(self.expected_depths)
                + ", got "
                + repr(actual_depths)
            )


__all__ = ["ReorderScenario"]
