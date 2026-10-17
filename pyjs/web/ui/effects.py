from typing import Final

from pyjs import JS, js
from pyjs.web.dom import Element

EFFECTS_CSS: Final[JS] = (
    "[data-scroll-fade]{"
    "--scroll-fade-size:2.5rem;"
    "--scroll-fade-start:0px;"
    "--scroll-fade-end:0px;"
    "-webkit-mask-image:linear-gradient("
    "to bottom,transparent 0,#000 var(--scroll-fade-start),"
    "#000 calc(100% - var(--scroll-fade-end)),transparent 100%);"
    "mask-image:linear-gradient("
    "to bottom,transparent 0,#000 var(--scroll-fade-start),"
    "#000 calc(100% - var(--scroll-fade-end)),transparent 100%);"
    "-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;}"
    "[data-scroll-fade='x']{"
    "-webkit-mask-image:linear-gradient("
    "to right,transparent 0,#000 var(--scroll-fade-start),"
    "#000 calc(100% - var(--scroll-fade-end)),transparent 100%);"
    "mask-image:linear-gradient("
    "to right,transparent 0,#000 var(--scroll-fade-start),"
    "#000 calc(100% - var(--scroll-fade-end)),transparent 100%);}"
    "@keyframes pyjs-shimmer{from{background-position:100% 0;}to{background-position:0 0;}}"
    "[data-shimmer]{"
    "--shimmer-spread:calc(3ch + 40px);"
    "background-image:linear-gradient("
    "90deg,currentColor calc(50% - var(--shimmer-spread)),"
    "color-mix(in srgb,currentColor 55%,white) 50%,"
    "currentColor calc(50% + var(--shimmer-spread)));"
    "background-size:calc(200% + var(--shimmer-spread) * 2) 100%;"
    "background-clip:text;-webkit-background-clip:text;"
    "-webkit-text-fill-color:transparent;"
    "animation:pyjs-shimmer 2s linear infinite;}"
    "@media (prefers-reduced-motion:reduce){"
    "[data-shimmer]{animation:none;background-image:none;"
    "-webkit-text-fill-color:currentColor;}}"
    "[data-pending-scroll='true'] [data-slot='message-scroller-viewport']{"
    "visibility:hidden;}"
    "[data-autoscrolling='true'] [data-slot='message-scroller-viewport']{"
    "scrollbar-color:transparent transparent;}"
    "[data-autoscrolling='true'] [data-slot='message-scroller-viewport']"
    "::-webkit-scrollbar-thumb{background:transparent;}"
)


@js
def sync_scroll_fade(element: Element, size: int = 40) -> None:
    horizontal = element.getAttribute("data-scroll-fade") == "x"
    if horizontal:
        overflowing = element.scrollWidth > element.clientWidth + 1
        start_offset = element.scrollLeft
        remaining = element.scrollWidth - element.scrollLeft - element.clientWidth
    else:
        overflowing = element.scrollHeight > element.clientHeight + 1
        start_offset = element.scrollTop
        remaining = element.scrollHeight - element.scrollTop - element.clientHeight
    start = 0
    end = 0
    if overflowing:
        if start_offset > 1:
            start = size
        if remaining > 1:
            end = size
    element.style.setProperty("--scroll-fade-start", str(start) + "px")
    element.style.setProperty("--scroll-fade-end", str(end) + "px")
