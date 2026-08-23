from collections.abc import Awaitable, Callable

from pyjs import js
from pyjs.javascript import Date
from pyjs.ui.interaction import InteractionSample, InteractionSampler

from . import (
    AnimationDefinition,
    EventData,
    GestureTypes,
    TouchGestureEventData,
    View,
    clearTimeout,
    setTimeout,
)
from .haptics import AndroidHapticFeedback, perform_haptic_feedback
from .masonry import MasonryLayout
from .simulator import (
    MasonryDragDecision,
    MasonryDragSession,
    MasonryViewportAnchor,
)


@js.inline("{listener}")
def _touch_listener(
    listener: object,
) -> Callable[[TouchGestureEventData], Awaitable[None]]:
    return listener


@js.inline("{listener}")
def _event_listener(listener: object) -> Callable[[EventData], None]:
    return listener


@js
class MasonryReorderResult:
    """The stable item order and columns committed by a masonry drag."""

    def __init__(
        self,
        source_id: str,
        item_ids: list[str],
        columns: list[int],
        column_count: int,
    ):
        self.source_id = source_id
        self.item_ids = item_ids
        self.columns = columns
        self.column_count = column_count


@js
class MasonryReorderController:
    """Connect NativeScript touch input to a masonry layout's drag model."""

    def __init__(
        self,
        layout: MasonryLayout,
        on_commit: Callable[[MasonryReorderResult], None],
        long_press_ms: int = 500,
        movement_threshold: float = 12,
        release_duration_ms: int = 0,
    ):
        self.layout = layout
        self.on_commit = on_commit
        self.long_press_ms = long_press_ms
        self.movement_threshold = movement_threshold
        self.release_duration_ms = release_duration_ms
        self.sampler = InteractionSampler()
        self.pending_timer: int | None = None
        self.auto_scroll_timer: int | None = None
        self.suppression_timer: int | None = None
        self.anchor_timer: int | None = None
        self.pending_id = ""
        self.pending_samples: list[InteractionSample] = []
        self.active_id = ""
        self.source_index = -1
        self.start_x = 0.0
        self.start_y = 0.0
        self.pointer_x = 0.0
        self.pointer_y = 0.0
        self.delta_x = 0.0
        self.delta_y = 0.0
        self.suppressed_tap_id = ""
        self.settling = False
        self.drag_anchor: MasonryViewportAnchor | None = None
        self.pending_anchor: MasonryViewportAnchor | None = None
        self.attached_views: list[View] = []
        self.touch_listener = _touch_listener(self.handle_touch)
        self.anchor_listener = _event_listener(self.restore_anchor)
        self.original_scroll_enabled = True
        self.changed_scroll_enabled = False
        self.original_opacity = 1.0
        self.original_scale_x = 1.0
        self.original_scale_y = 1.0
        self.original_elevation = 0
        self.original_border_width: int | float | str = 0
        self.original_border_color = ""
        self.attach()

    def attach(self):
        self.detach()
        for view in self.layout.item_views:
            view.on(GestureTypes.touch, self.touch_listener)
            self.attached_views.append(view)
            if view.accessibilityHint == "":
                view.accessibilityHint = "Long press and drag to reorder"

    def detach(self):
        for view in self.attached_views:
            view.off(GestureTypes.touch, self.touch_listener)
        self.attached_views = []

    def dispose(self):
        self.cancel()
        self.clear_suppression()
        self.clear_anchor_restore()
        self.detach()

    def item_index(self, item_id: str) -> int:
        for index in range(len(self.layout.item_views)):
            if self.layout.item_views[index].id == item_id:
                return index
        return -1

    def item_view(self, item_id: str) -> View | None:
        index = self.item_index(item_id)
        if index < 0:
            return None
        return self.layout.item_views[index]

    def clear_pending_timer(self):
        if self.pending_timer is not None:
            clearTimeout(self.pending_timer)
        self.pending_timer = None
        self.pending_id = ""
        self.pending_samples = []

    def clear_auto_scroll(self):
        if self.auto_scroll_timer is not None:
            clearTimeout(self.auto_scroll_timer)
        self.auto_scroll_timer = None

    def clear_suppression(self):
        if self.suppression_timer is not None:
            clearTimeout(self.suppression_timer)
        self.suppression_timer = None
        self.suppressed_tap_id = ""

    def consume_suppressed_tap(self, item_id: str) -> bool:
        if self.suppressed_tap_id != item_id:
            return False
        self.clear_suppression()
        return True

    def suppress_active_tap(self):
        self.clear_suppression()
        self.suppressed_tap_id = self.active_id
        self.suppression_timer = setTimeout(self.clear_suppression, 500)

    def remember_style(self, view: View):
        self.original_opacity = view.opacity
        self.original_scale_x = view.scaleX
        self.original_scale_y = view.scaleY
        self.original_elevation = view.androidElevation
        self.original_border_width = view.borderWidth
        self.original_border_color = view.borderColor

    def style_active_view(self, view: View, changes_layout: bool):
        view.opacity = 0.94
        view.scaleX = 1.03
        view.scaleY = 1.03
        view.androidElevation = 16
        view.borderWidth = 2
        view.borderColor = "#2563eb" if changes_layout else "#64748b"

    def restore_active_style(self, view: View):
        view.opacity = self.original_opacity
        view.scaleX = self.original_scale_x
        view.scaleY = self.original_scale_y
        view.androidElevation = self.original_elevation
        view.borderWidth = self.original_border_width
        view.borderColor = self.original_border_color

    def restore_active_view(self, view: View):
        self.restore_active_style(view)
        view.translateX = 0.0
        view.translateY = 0.0

    def begin_pending_drag(self):
        item_id = self.pending_id
        samples = self.pending_samples
        self.pending_timer = None
        self.pending_id = ""
        self.pending_samples = []
        source_index = self.item_index(item_id)
        view = self.item_view(item_id)
        if source_index < 0 or not isinstance(view, View):
            return
        if self.sampler.active:
            samples.append(
                self.sampler.sample(
                    "hold",
                    self.pointer_x,
                    self.pointer_y,
                    Date.now(),
                )
            )
        self.original_scroll_enabled = self.layout.isScrollEnabled
        self.changed_scroll_enabled = True
        self.layout.isScrollEnabled = False
        self.layout.start_simulated_drag(
            source_index,
            self.start_x,
            self.start_y,
            samples,
        )
        if not isinstance(self.layout.drag_session, MasonryDragSession):
            self.restore_scroll_enabled()
            return
        self.active_id = item_id
        self.source_index = source_index
        if self.layout.verticalOffset > 0:
            self.drag_anchor = self.layout.capture_viewport_anchor(item_id)
        self.remember_style(view)
        self.style_active_view(view, False)
        perform_haptic_feedback(view, AndroidHapticFeedback.longPress)

    def drag_changes_layout(self) -> bool:
        session = self.layout.drag_session
        decision = self.layout.drag_decision
        if not isinstance(session, MasonryDragSession) or not isinstance(
            decision,
            MasonryDragDecision,
        ):
            return False
        if self.source_index < 0 or self.source_index >= len(session.items):
            return False
        return (
            decision.destination_index != self.source_index
            or decision.destination_column
            != session.original_layout.columns[self.source_index]
        )

    def update_drag(self, sample: InteractionSample | None = None):
        previous_scroll = self.layout.verticalOffset
        decision = self.layout.update_simulated_drag(
            self.pointer_x,
            self.pointer_y,
            sample=sample,
        )
        self.delta_x = self.pointer_x - self.start_x
        self.delta_y = self.pointer_y - self.start_y
        view = self.item_view(self.active_id)
        if isinstance(decision, MasonryDragDecision) and isinstance(view, View):
            self.style_active_view(view, self.drag_changes_layout())
        if (
            previous_scroll != self.layout.verticalOffset
            and self.auto_scroll_timer is None
        ):
            self.auto_scroll_timer = setTimeout(self.continue_auto_scroll, 50)

    def continue_auto_scroll(self):
        self.auto_scroll_timer = None
        if self.active_id == "":
            return
        sample: InteractionSample | None = None
        if self.sampler.active:
            sample = self.sampler.sample(
                "hold",
                self.pointer_x,
                self.pointer_y,
                Date.now(),
            )
        self.update_drag(sample)

    def reordered_values(
        self,
        item_ids: list[str],
        columns: list[int],
    ) -> tuple[list[View], list[float], list[str], list[int]]:
        views: list[View] = []
        heights: list[float] = []
        groups: list[str] = []
        assigned_columns: list[int] = []
        views_by_id: dict[str, View] = {}
        heights_by_id: dict[str, float] = {}
        groups_by_id: dict[str, str] = {}
        for index in range(len(self.layout.item_views)):
            item_id = self.layout.item_views[index].id
            views_by_id[item_id] = self.layout.item_views[index]
            height = 1.0
            if index < len(self.layout.estimated_heights):
                height = self.layout.estimated_heights[index]
            heights_by_id[item_id] = height
            groups_by_id[item_id] = self.layout.item_groups[index]
        for item_index in range(len(item_ids)):
            item_id = item_ids[item_index]
            views.append(views_by_id[item_id])
            heights.append(heights_by_id[item_id])
            groups.append(groups_by_id[item_id])
            assigned_columns.append(columns[item_index])
        return views, heights, groups, assigned_columns

    def clear_anchor_restore(self):
        if self.anchor_timer is not None:
            clearTimeout(self.anchor_timer)
        self.anchor_timer = None
        if self.pending_anchor is not None:
            self.layout.off(View.layoutChangedEvent, self.anchor_listener)
        self.pending_anchor = None

    def schedule_anchor_restore(self, anchor: MasonryViewportAnchor | None):
        if not isinstance(anchor, MasonryViewportAnchor):
            return
        self.clear_anchor_restore()
        self.pending_anchor = anchor
        self.layout.on(View.layoutChangedEvent, self.anchor_listener)
        self.anchor_timer = setTimeout(self.restore_anchor, 50)

    def restore_anchor(self, event: EventData | None = None):
        if event is not None:
            if self.anchor_timer is not None:
                clearTimeout(self.anchor_timer)
            self.anchor_timer = setTimeout(self.restore_anchor, 50)
            return
        anchor = self.pending_anchor
        self.clear_anchor_restore()
        if isinstance(anchor, MasonryViewportAnchor):
            self.layout.restore_viewport_anchor(anchor)

    def restore_scroll_enabled(self):
        if self.changed_scroll_enabled:
            self.layout.isScrollEnabled = self.original_scroll_enabled
        self.changed_scroll_enabled = False

    async def finish_drag(self):
        if self.settling:
            return
        view = self.item_view(self.active_id)
        if not isinstance(view, View):
            self.cancel()
            return
        self.suppress_active_tap()
        moved = abs(self.delta_x) + abs(self.delta_y) >= self.movement_threshold
        changed = moved and self.drag_changes_layout()
        item_ids = self.layout.simulated_item_ids()
        columns = self.layout.simulated_columns()
        result = MasonryReorderResult(
            self.active_id,
            item_ids,
            columns,
            self.layout.column_count,
        )
        anchor = self.drag_anchor
        translation_x = 0.0
        translation_y = 0.0
        if changed:
            translation = self.layout.simulated_drop_translation(self.active_id)
            translation_x = translation.x
            translation_y = translation.y
        self.layout.commit_simulated_drag(anchor)
        values = self.reordered_values(item_ids, columns)
        excluded_index = -1
        if self.release_duration_ms > 0:
            excluded_index = self.source_index
        self.layout.clear_simulated_drag(excluded_index)
        self.restore_scroll_enabled()
        self.active_id = ""
        self.source_index = -1
        self.drag_anchor = None
        self.clear_auto_scroll()
        self.sampler.active = False
        self.settling = True
        try:
            if self.release_duration_ms > 0:
                self.restore_active_style(view)
                options: AnimationDefinition = {
                    "translate": {"x": translation_x, "y": translation_y},
                    "scale": {
                        "x": self.original_scale_x,
                        "y": self.original_scale_y,
                    },
                    "opacity": self.original_opacity,
                    "duration": self.release_duration_ms,
                    "curve": "easeOut",
                }
                try:
                    await view.animate(options)
                except Exception:
                    pass
            if changed:
                self.layout.set_items(values[0], values[1], values[2], values[3])
                self.schedule_anchor_restore(anchor)
                perform_haptic_feedback(view, AndroidHapticFeedback.virtualKey)
                self.on_commit(result)
        finally:
            self.restore_active_view(view)
            self.settling = False

    def cancel(self, sample: InteractionSample | None = None):
        if (
            sample is None
            and self.sampler.active
            and self.layout.drag_session is not None
        ):
            sample = self.sampler.sample(
                "cancel",
                self.pointer_x,
                self.pointer_y,
                Date.now(),
            )
        self.clear_pending_timer()
        self.clear_auto_scroll()
        view = self.item_view(self.active_id)
        if self.active_id != "" or self.layout.drag_session is not None:
            self.layout.clear_simulated_drag(sample=sample)
        self.restore_scroll_enabled()
        if isinstance(view, View):
            self.restore_active_view(view)
        self.active_id = ""
        self.source_index = -1
        self.drag_anchor = None
        self.delta_x = 0.0
        self.delta_y = 0.0
        self.sampler.active = False

    async def handle_touch(self, event: TouchGestureEventData):
        if self.settling:
            return
        view = event.object
        if not isinstance(view, View):
            return
        if event.action == "down":
            self.cancel()
            down = self.sampler.begin(event.getRawX(), event.getRawY(), Date.now())
            self.pending_id = view.id
            self.pending_samples = [down]
            self.start_x = event.getRawX()
            self.start_y = event.getRawY()
            self.pointer_x = self.start_x
            self.pointer_y = self.start_y
            self.pending_timer = setTimeout(
                self.begin_pending_drag,
                self.long_press_ms,
            )
            return
        self.pointer_x = event.getRawX()
        self.pointer_y = event.getRawY()
        sample: InteractionSample | None = None
        if self.sampler.active:
            sample = self.sampler.sample(
                event.action,
                self.pointer_x,
                self.pointer_y,
                Date.now(),
            )
        if self.active_id == "":
            delta_x = self.pointer_x - self.start_x
            delta_y = self.pointer_y - self.start_y
            if sample is not None:
                self.pending_samples.append(sample)
            if (
                abs(delta_x) + abs(delta_y) >= self.movement_threshold
                or event.action == "up"
                or event.action == "cancel"
            ):
                self.clear_pending_timer()
                self.sampler.active = False
            return
        if view.id != self.active_id:
            return
        if event.action == "move":
            self.update_drag(sample)
        elif event.action == "up":
            self.update_drag(sample)
            await self.finish_drag()
        elif event.action == "cancel":
            self.cancel(sample)


__all__ = ["MasonryReorderController", "MasonryReorderResult"]
