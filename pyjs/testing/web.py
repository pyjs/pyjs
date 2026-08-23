"""Small helpers for browser-compiled UI tests."""

from typing import cast

from pyjs import js
from pyjs.testing.client.runtime import window
from pyjs.testing.client.state import RenderArtifact
from pyjs.ui.interaction import InteractionSample
from pyjs.web.dom import Element, Node, document
from pyjs.web.dragdrop import DataTransfer, DragEvent
from pyjs.web.events import Event, EventTarget, KeyboardEvent, PointerEvent

from .interaction.gesture import GestureScript, InteractionClock


@js
def mount(*elements: Node):
    document.body.replaceChildren()
    document.body.style.margin = "0px"
    document.body.style.overflow = "visible"
    document.body.append(*elements)


@js
def bubbling_click(target: EventTarget):
    target.dispatchEvent(Event("click", bubbles=True))


@js
def press_key(target: EventTarget, key: str):
    target.dispatchEvent(KeyboardEvent("keydown", key=key, bubbles=True))


@js
def dispatch_pointer_sample(target: EventTarget, sample: InteractionSample):
    event_name = "pointermove"
    if sample.phase == "down":
        event_name = "pointerdown"
    elif sample.phase == "up":
        event_name = "pointerup"
    elif sample.phase == "cancel":
        event_name = "pointercancel"
    buttons = 1
    if sample.phase == "up" or sample.phase == "cancel":
        buttons = 0
    target.dispatchEvent(
        PointerEvent(
            event_name,
            bubbles=True,
            cancelable=True,
            clientX=int(sample.x),
            clientY=int(sample.y),
            movementX=sample.delta_x,
            movementY=sample.delta_y,
            pointerId=sample.pointer_id,
            buttons=buttons,
        )
    )


@js
def dispatch_pointer_script(
    target: EventTarget,
    script: GestureScript,
    clock: InteractionClock | None = None,
):
    start = 0.0
    if clock is not None:
        start = clock.now()
    for sample in script.samples:
        if clock is not None:
            clock.seek(start + sample.elapsed_ms)
        dispatch_pointer_sample(target, sample)


@js
def _dispatch_drag_event(
    target: EventTarget,
    name: str,
    sample: InteractionSample,
    transfer: DataTransfer,
    cancelable: bool = False,
) -> None:
    target.dispatchEvent(
        DragEvent(
            name,
            bubbles=True,
            cancelable=cancelable,
            clientX=int(sample.x),
            clientY=int(sample.y),
            dataTransfer=transfer,
        )
    )


@js
def dispatch_drag_script(
    source: Element,
    script: GestureScript,
    target_at: callable | None = None,
) -> DataTransfer:
    """Dispatch an HTML drag lifecycle from a target-neutral gesture script.

    Browsers intentionally do not promote synthetic pointer events to trusted
    native drags. This test adapter emits the corresponding HTML drag events;
    callers may override hit testing for shadow DOM or virtualized layouts.
    """

    transfer = DataTransfer()
    current_target: Element | None = None
    active = False
    for sample in script.samples:
        if sample.phase == "down":
            _dispatch_drag_event(source, "dragstart", sample, transfer, True)
            current_target = source
            active = True
        elif active and sample.phase == "move":
            target: Element | None = None
            if target_at is not None:
                target = cast(Element | None, target_at(sample))
            else:
                target = document.elementFromPoint(sample.x, sample.y)
            if target is None:
                target = current_target
            if target is not current_target:
                if current_target is not None:
                    _dispatch_drag_event(
                        current_target,
                        "dragleave",
                        sample,
                        transfer,
                    )
                if target is not None:
                    _dispatch_drag_event(target, "dragenter", sample, transfer, True)
                current_target = target
            if current_target is not None:
                _dispatch_drag_event(
                    current_target,
                    "dragover",
                    sample,
                    transfer,
                    True,
                )
        elif active and sample.phase == "up":
            if current_target is not None:
                _dispatch_drag_event(current_target, "drop", sample, transfer, True)
            _dispatch_drag_event(source, "dragend", sample, transfer)
            active = False
        elif active and sample.phase == "cancel":
            _dispatch_drag_event(source, "dragend", sample, transfer)
            active = False
    return transfer


@js
def selector_count(root: Element, selector: str) -> int:
    return len(root.querySelectorAll(selector))


@js.inline("new Promise((resolve) => requestAnimationFrame(resolve))")
async def next_frame() -> None: ...


@js
async def wait_for_frames(count: int = 2) -> None:
    """Wait for the browser to complete one or more rendering frames."""
    for _ in range(count):
        await next_frame()


@js
async def wait_for_settled_phase(
    clock: InteractionClock,
    name: str,
    max_frames: int = 60,
) -> None:
    for _ in range(max_frames):
        if clock.is_settled(name):
            return
        await next_frame()
    raise ValueError("Interaction phase '" + name + "' did not settle.")


@js
async def wait_for_event(
    target: EventTarget,
    event_name: str,
    trigger: callable | None = None,
) -> Event: ...


@wait_for_event.inline
def wait_for_event(_arg_strs, **kwargs):
    target, event_name = _arg_strs[:2]
    trigger = f"{_arg_strs[2]}();" if len(_arg_strs) == 3 else ""
    return (
        "new Promise((resolve) => {"
        f"{target}.addEventListener({event_name}, resolve, {{once: true}});"
        f"{trigger}"
        "})"
    )


@js
def assert_render(
    element: Element,
    name: str,
    pixel_threshold: int = 8,
    max_different_pixel_ratio: float = 0.01,
    animation_time_ms: float | None = None,
):
    """Compare an element's rendered pixels with a stored image."""
    artifacts = window.__pyjsRenderArtifacts__
    element_id = "render-" + str(len(artifacts))
    element_ids = element.getAttribute("data-pyjs-render")
    if element_ids is None:
        element_ids = element_id
    else:
        element_ids += " " + element_id
    element.setAttribute("data-pyjs-render", element_ids)
    artifacts.append(
        RenderArtifact(
            name,
            "",
            pixel_threshold,
            max_different_pixel_ratio,
            element_id,
            animation_time_ms,
        )
    )
