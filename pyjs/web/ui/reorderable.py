from pyjs import js
from pyjs.ui.interaction import (
    InteractionMeasurement,
    InteractionSample,
    InteractionViewport,
)
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderDecision,
    ReorderItem,
    ReorderObserver,
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
        observer: ReorderObserver | None = None,
    ):
        self.container = container
        self.item_attribute = item_attribute
        self.engine = HierarchicalReorder(max_depth, indent_step)
        self.session: ReorderSession | None = None
        self.decision: ReorderDecision | None = None
        self.hidden_elements: list[HTMLElement] = []
        self.hidden_values: list[bool | float | str | None] = []
        self.active_elements: list[HTMLElement] = []
        self.elements_by_id: dict[str, HTMLElement] = {}
        self.rows: list[ReorderRow] = []
        self.rows_scroll_top = 0.0
        self.observer = observer

    def item_elements(self) -> list[HTMLElement]:
        elements: list[HTMLElement] = []
        selector = "[" + self.item_attribute + "]"
        for candidate in self.container.querySelectorAll(selector):
            if isinstance(candidate, HTMLElement):
                elements.append(candidate)
        return elements

    def element_for(self, item_id: str) -> HTMLElement | None:
        if item_id in self.elements_by_id:
            return self.elements_by_id[item_id]
        for element in self.item_elements():
            if element.getAttribute(self.item_attribute) == item_id:
                return element
        return None

    def refresh_geometry(self) -> list[ReorderRow]:
        """Remeasure stable row geometry after an application layout change."""

        self.rows = []
        session = self.session
        if not isinstance(session, ReorderSession):
            return self.rows
        for item in session.remaining_items:
            element = self.element_for(item.id)
            if isinstance(element, HTMLElement):
                bounds = element.getBoundingClientRect()
                self.rows.append(ReorderRow(item.id, bounds.top, bounds.height))
        self.rows_scroll_top = self.container.scrollTop
        return self.rows

    def current_rows(self) -> list[ReorderRow]:
        if len(self.rows) == 0:
            return self.refresh_geometry()
        scroll_delta = self.container.scrollTop - self.rows_scroll_top
        if scroll_delta == 0:
            return self.rows
        adjusted: list[ReorderRow] = []
        for row in self.rows:
            adjusted.append(ReorderRow(row.id, row.start - scroll_delta, row.size))
        return adjusted

    def begin(
        self,
        items: list[ReorderItem],
        source_index: int,
        samples: list[InteractionSample] | None = None,
    ) -> ReorderSession | None:
        self.clear()
        session = self.engine.begin(items, source_index)
        observer = self.observer
        if observer is not None:
            observer.started(self.engine, items, source_index, session, samples)
        if not isinstance(session, ReorderSession):
            return None
        self.session = session
        self.active_elements = self.item_elements()
        self.elements_by_id = {}
        for active_element in self.active_elements:
            item_id = active_element.getAttribute(self.item_attribute)
            if item_id is not None and item_id not in self.elements_by_id:
                self.elements_by_id[item_id] = active_element
        self.container.setAttribute("data-reorder-source", session.source.id)
        for item_id in session.hidden_item_ids:
            hidden_element = self.element_for(item_id)
            if isinstance(hidden_element, HTMLElement):
                self.hidden_elements.append(hidden_element)
                self.hidden_values.append(hidden_element.hidden)
                hidden_element.hidden = True
        self.refresh_geometry()
        self.decision = session.preview(source_index, session.source_depth)
        return session

    def update(
        self,
        pointer: float,
        horizontal_delta: float,
        sample: InteractionSample | None = None,
        rows: list[ReorderRow] | None = None,
    ) -> ReorderDecision | None:
        session = self.session
        if not isinstance(session, ReorderSession):
            return None
        if rows is None:
            rows = self.current_rows()
        decision = session.update(rows, pointer, horizontal_delta)
        self.decision = decision
        self.container.setAttribute(
            "data-reorder-depth",
            str(decision.target_depth),
        )
        observer = self.observer
        if observer is not None:
            viewport_bounds = self.container.getBoundingClientRect()
            measurements: list[InteractionMeasurement] = []
            for element in self.active_elements:
                item_id = element.getAttribute(self.item_attribute)
                if item_id is None:
                    continue
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
            observer.updated(
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
        sample: InteractionSample | None = None,
        scroll_anchor_id: str = "",
        scroll_anchor_offset: float = 0,
    ) -> ReorderDecision | None:
        decision = self.decision
        if not isinstance(decision, ReorderDecision):
            return None
        observer = self.observer
        if observer is not None:
            observer.committed(
                decision,
                scroll_anchor_id,
                scroll_anchor_offset,
                sample=sample,
            )
        return decision

    def clear(self, sample: InteractionSample | None = None):
        observer = self.observer
        if observer is not None:
            observer.cancelled(sample)
        for index in range(len(self.hidden_elements)):
            self.hidden_elements[index].hidden = self.hidden_values[index]
        self.container.removeAttribute("data-reorder-source")
        self.container.removeAttribute("data-reorder-depth")
        self.session = None
        self.decision = None
        self.hidden_elements = []
        self.hidden_values = []
        self.active_elements = []
        self.elements_by_id = {}
        self.rows = []
        self.rows_scroll_top = 0.0


__all__ = ["ReorderableOutlineController"]
