from pyjs import js
from pyjs.ui.gesture import GestureScript
from pyjs.ui.interaction import (
    InteractionMeasurement,
    InteractionSample,
    InteractionViewport,
)
from pyjs.ui.reorder_trace import ReorderTraceRecorder
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderDecision,
    ReorderItem,
    ReorderRow,
    ReorderSession,
)
from pyjs.web.dom import Element
from pyjs.web.html import HTMLElement


@js
class ReorderableOutlineController:
    """DOM geometry and collapsed descendants for hierarchical reordering."""

    def __init__(
        self,
        container: Element,
        item_attribute: str = "data-reorder-id",
        max_depth: int = 5,
        indent_step: float = 36,
        recorder: ReorderTraceRecorder | None = None,
    ):
        self.container = container
        self.item_attribute = item_attribute
        self.engine = HierarchicalReorder(max_depth, indent_step)
        self.session: ReorderSession | None = None
        self.decision: ReorderDecision | None = None
        self.hidden_elements: list[HTMLElement] = []
        self.hidden_values: list[bool | float | str | None] = []
        self.recorder = recorder

    def record_interactions(self, redact_ids: bool = True) -> ReorderTraceRecorder:
        recorder = ReorderTraceRecorder(redact_ids, {"platform": "web"})
        self.recorder = recorder
        return recorder

    def item_elements(self) -> list[HTMLElement]:
        elements: list[HTMLElement] = []
        selector = "[" + self.item_attribute + "]"
        for candidate in self.container.querySelectorAll(selector):
            if isinstance(candidate, HTMLElement):
                elements.append(candidate)
        return elements

    def element_for(self, item_id: str) -> HTMLElement | None:
        for element in self.item_elements():
            if element.getAttribute(self.item_attribute) == item_id:
                return element
        return None

    def begin(
        self,
        items: list[ReorderItem],
        source_index: int,
    ) -> ReorderSession | None:
        self.clear()
        recorder = self.recorder
        if isinstance(recorder, ReorderTraceRecorder):
            session = recorder.begin(self.engine, items, source_index)
        else:
            session = self.engine.begin(items, source_index)
        if not isinstance(session, ReorderSession):
            return None
        self.session = session
        self.container.setAttribute("data-reorder-source", session.source.id)
        for item_id in session.hidden_item_ids:
            element = self.element_for(item_id)
            if isinstance(element, HTMLElement):
                self.hidden_elements.append(element)
                self.hidden_values.append(element.hidden)
                element.hidden = True
        self.decision = session.preview(source_index, session.source_depth)
        return session

    def update(
        self,
        pointer: float,
        horizontal_delta: float,
        sample: InteractionSample | None = None,
    ) -> ReorderDecision | None:
        session = self.session
        if not isinstance(session, ReorderSession):
            return None
        rows: list[ReorderRow] = []
        for item in session.remaining_items:
            element = self.element_for(item.id)
            if isinstance(element, HTMLElement):
                bounds = element.getBoundingClientRect()
                rows.append(ReorderRow(item.id, bounds.top, bounds.height))
        decision = session.update(rows, pointer, horizontal_delta)
        self.decision = decision
        self.container.setAttribute(
            "data-reorder-depth",
            str(decision.target_depth),
        )
        recorder = self.recorder
        if isinstance(recorder, ReorderTraceRecorder):
            viewport_bounds = self.container.getBoundingClientRect()
            measurements: list[InteractionMeasurement] = []
            for element in self.item_elements():
                item_id = element.getAttribute(self.item_attribute)
                bounds = element.getBoundingClientRect()
                clipped = (
                    bounds.top < viewport_bounds.top
                    or bounds.left < viewport_bounds.left
                    or bounds.top + bounds.height
                    > viewport_bounds.top + viewport_bounds.height
                    or bounds.left + bounds.width
                    > viewport_bounds.left + viewport_bounds.width
                )
                measurements.append(
                    InteractionMeasurement(
                        item_id,
                        bounds.left,
                        bounds.top,
                        bounds.width,
                        bounds.height,
                        clipped,
                    )
                )
            recorder.record_update(
                rows,
                pointer,
                horizontal_delta,
                decision,
                sample=sample,
                measurements=measurements,
                viewport=InteractionViewport(
                    viewport_bounds.left,
                    viewport_bounds.top,
                    viewport_bounds.width,
                    viewport_bounds.height,
                    self.container.scrollLeft,
                    self.container.scrollTop,
                    self.container.scrollWidth,
                    self.container.scrollHeight,
                ),
            )
        return decision

    def commit(
        self,
        scroll_anchor_id: str = "",
        scroll_anchor_offset: float = 0,
    ) -> ReorderDecision | None:
        decision = self.decision
        if not isinstance(decision, ReorderDecision):
            return None
        recorder = self.recorder
        if isinstance(recorder, ReorderTraceRecorder):
            recorder.record_commit(
                decision,
                scroll_anchor_id,
                scroll_anchor_offset,
            )
        return decision

    def play_gesture(self, script: GestureScript) -> ReorderDecision | None:
        start_x = 0.0
        active = False
        decision: ReorderDecision | None = None
        for sample in script.samples:
            if sample.phase == "down":
                start_x = sample.x
                active = True
            elif active and (sample.phase == "hold" or sample.phase == "move"):
                decision = self.update(
                    sample.y,
                    sample.x - start_x,
                    sample,
                )
            elif sample.phase == "up":
                decision = self.commit()
                active = False
            elif sample.phase == "cancel":
                self.clear()
                decision = None
                active = False
        return decision

    def clear(self):
        for index in range(len(self.hidden_elements)):
            self.hidden_elements[index].hidden = self.hidden_values[index]
        self.container.removeAttribute("data-reorder-source")
        self.container.removeAttribute("data-reorder-depth")
        self.session = None
        self.decision = None
        self.hidden_elements = []
        self.hidden_values = []


__all__ = ["ReorderableOutlineController"]
