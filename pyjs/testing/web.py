"""Small helpers for browser-compiled UI tests."""

from pyjs import js
from pyjs.testing.client.runtime import window
from pyjs.testing.client.state import RenderArtifact
from pyjs.web.dom import Element, Node, document
from pyjs.web.events import Event, EventTarget, KeyboardEvent


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
def selector_count(root: Element, selector: str) -> int:
    return len(root.querySelectorAll(selector))


@js(builtin=True, inline="new Promise((resolve) => requestAnimationFrame(resolve))")
async def next_frame() -> None: ...


@js
async def wait_for_frames(count: int = 2) -> None:
    """Wait for the browser to complete one or more rendering frames."""
    for _ in range(count):
        await next_frame()


def _rewrite_wait_for_event(_arg_strs, **kwargs):
    target, event_name = _arg_strs[:2]
    trigger = f"{_arg_strs[2]}();" if len(_arg_strs) == 3 else ""
    return (
        "new Promise((resolve) => {"
        f"{target}.addEventListener({event_name}, resolve, {{once: true}});"
        f"{trigger}"
        "})"
    )


@js(builtin=True, inline=_rewrite_wait_for_event)
async def wait_for_event(
    target: EventTarget,
    event_name: str,
    trigger: callable | None = None,
) -> Event: ...


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
