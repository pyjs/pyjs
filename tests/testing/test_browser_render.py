import pytest

from pyjs import js
from pyjs.testing.web import assert_render, mount, wait_for_frames
from pyjs.web.dom import document


@pytest.mark.pyjs_web
@js
def test_element_render():
    card = document.createElement("section")
    card.setAttribute(
        "style",
        "box-sizing:border-box;width:180px;height:112px;padding:16px;"
        "border:4px solid #38bdf8;border-radius:16px;background:#0f172a",
    )
    accent = document.createElement("div")
    accent.setAttribute(
        "style",
        "width:72px;height:16px;border-radius:8px;background:#f8fafc",
    )
    detail = document.createElement("div")
    detail.setAttribute(
        "style",
        "width:132px;height:32px;margin-top:16px;border-radius:8px;background:#8b5cf6",
    )
    card.append(accent, detail)
    mount(card)

    assert_render(card, "dom-element")


@pytest.mark.pyjs_web
@js
async def test_animation_render_at_exact_time():
    styles = document.createElement("style")
    styles.textContent = "@keyframes pyjs-grow { from { width:24px } to { width:144px } }"
    document.head.append(styles)
    card = document.createElement("section")
    card.setAttribute(
        "style",
        "box-sizing:border-box;width:180px;height:80px;padding:16px;"
        "border-radius:16px;background:#172554",
    )
    bar = document.createElement("div")
    bar.setAttribute(
        "style",
        "height:48px;border-radius:8px;background:#fbbf24;"
        "animation:pyjs-grow 1000ms linear infinite",
    )
    card.append(bar)
    mount(card)
    await wait_for_frames()

    assert_render(card, "dom-animation-start", animation_time_ms=0)
    assert_render(card, "dom-animation-midpoint", animation_time_ms=500)
