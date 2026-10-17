from pyjs import js
from pyjs.web.domx import div
from pyjs.web.events import WheelEvent
from pyjs.web.ui.message_scroller import MessageScroller, MessageScrollerItem


@js
def tall_item(label: str, height: int, scroll_anchor: bool = False, message_id: str = ""):
    return MessageScrollerItem(
        div({"style": "height:" + str(height) + "px;flex:none"}, label),
        scroll_anchor=scroll_anchor,
        message_id=message_id,
    )


@js
def constrain_scroller(scroller: MessageScroller, height: int) -> None:
    scroller.setAttribute("style", "height:" + str(height) + "px")
    scroller.viewport.setAttribute(
        "style",
        "height:" + str(height) + "px;max-height:" + str(height) + "px",
    )
    scroller.content.setAttribute("style", "gap:0;padding:0;min-height:0")


@js
def dispatch_wheel(scroller: MessageScroller, delta_y: int) -> None:
    scroller.viewport.dispatchEvent(
        WheelEvent("wheel", deltaY=delta_y, bubbles=True, cancelable=True)
    )
