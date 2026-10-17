from typing import Final

from pyjs import JS, js
from pyjs.web.domx import div, tag, tw

TYPESET_CSS: Final[JS] = (
    "[data-slot='typeset']{"
    "--typeset-size:1em;--typeset-leading:1.75;--typeset-flow:1.25em;"
    "font-size:var(--typeset-size);line-height:var(--typeset-leading);"
    "overflow-wrap:break-word;}"
    "[data-slot='typeset'][data-preset='chat']{"
    "--typeset-leading:1.6;--typeset-flow:1em;font-size:0.95em;}"
    "[data-slot='typeset'][data-preset='docs']{"
    "--typeset-size:15px;--typeset-leading:1.75;--typeset-flow:1.5em;}"
    "[data-slot='typeset'] > :first-child{margin-block-start:0;}"
    "[data-slot='typeset'] p{margin-block-start:var(--typeset-flow);margin-block-end:0;}"
    "[data-slot='typeset'] h1,[data-slot='typeset'] h2,[data-slot='typeset'] h3,"
    "[data-slot='typeset'] h4,[data-slot='typeset'] h5,[data-slot='typeset'] h6{"
    "font-weight:600;margin-block-end:0;}"
    "[data-slot='typeset'] h1{font-size:1.75em;line-height:1.3;"
    "margin-block-start:var(--typeset-flow);}"
    "[data-slot='typeset'] h2{font-size:1.25em;line-height:1.4;"
    "margin-block-start:calc(var(--typeset-flow) * 1.4);}"
    "[data-slot='typeset'] h3{font-size:1.125em;line-height:1.45;"
    "margin-block-start:var(--typeset-flow);}"
    "[data-slot='typeset'] h4{font-size:1em;margin-block-start:var(--typeset-flow);}"
    "[data-slot='typeset'] ul,[data-slot='typeset'] ol{"
    "margin-block-start:var(--typeset-flow);padding-inline-start:1.5em;}"
    "[data-slot='typeset'] li{margin-block-start:0.35em;}"
    "[data-slot='typeset'] pre{margin-block-start:var(--typeset-flow);"
    "padding:0.75em 1em;overflow-x:auto;border-radius:0.5em;"
    "background:color-mix(in srgb,currentColor 8%,transparent);}"
    "[data-slot='typeset'] code{font-family:ui-monospace,monospace;font-size:0.9em;}"
    "[data-slot='typeset'] blockquote{margin-block-start:var(--typeset-flow);"
    "padding-inline-start:1em;border-inline-start:2px solid "
    "color-mix(in srgb,currentColor 20%,transparent);}"
    "[data-slot='typeset'] hr{margin-block-start:var(--typeset-flow);border:0;"
    "border-top:1px solid color-mix(in srgb,currentColor 20%,transparent);}"
    "[data-slot='typeset'] a{font-weight:500;text-decoration:underline;}"
    "[data-slot='typeset'] table{margin-block-start:var(--typeset-flow);"
    "border-collapse:collapse;width:100%;}"
    "[data-slot='typeset'] th,[data-slot='typeset'] td{"
    "border:1px solid color-mix(in srgb,currentColor 18%,transparent);"
    "padding:0.35em 0.6em;text-align:left;}"
)


@js
def Typeset(*children, preset: str = "docs"):
    return div(
        tw("min-w-0"),
        {"data-preset": preset, "data-slot": "typeset"},
        tag("style", TYPESET_CSS),
        *children,
    )
