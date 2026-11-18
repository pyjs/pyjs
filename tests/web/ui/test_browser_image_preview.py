from typing import cast

import pytest

from pyjs import js
from pyjs.testing.web import mount, wait_for_frames
from pyjs.web.dom import document, window
from pyjs.web.domx import a, button, div, img, span
from pyjs.web.files import Blob
from pyjs.web.html import OffscreenCanvas, OffscreenCanvasRenderingContext2D
from pyjs.web.ui.image_preview import ImagePreview, ImagePreviewQueue
from tests.web.ui.browser import place_element

pytestmark = pytest.mark.pyjs_web


@js
class ImageSource:
    def __init__(self):
        self.calls = 0
        self.hold = False
        self.fail = False

    async def load(self) -> Blob:
        self.calls += 1
        while self.hold:
            await wait_for_frames(1)
        if self.fail:
            return Blob(["not an image"], type="image/png")
        canvas = OffscreenCanvas(320, 160)
        context = canvas.getContext("2d")
        assert isinstance(context, OffscreenCanvasRenderingContext2D)
        context.fillStyle = "#2685a0"
        context.fillRect(0, 0, 320, 160)
        return await canvas.convertToBlob()


@js
async def expect_state(preview: ImagePreview, value: str):
    for _ in range(120):
        if preview.get_data("state") == value:
            return
        await wait_for_frames(1)
    assert preview.get_data("state") == value, (
        "Expected " + value + ", got " + (preview.get_data("state") or "<unset>")
        + "; initialized=" + str(preview._initialized)
        + "; visible=" + str(preview._visible)
    )


@js
async def test_preview_defers_reads_releases_offscreen_and_bounds_decoded_pixels():
    source = ImageSource()
    preview = ImagePreview(alt="Generated landscape", max_width=80, max_height=60)
    preview.load_with(source.load)
    place_element(preview, 0, 5000, 240, 160)
    mount(preview)
    await wait_for_frames(3)
    assert source.calls == 0
    assert preview.picture.getAttribute("src") is None
    place_element(preview, 0, 0, 240, 160)
    await expect_state(preview, "ready")
    assert source.calls == 1
    assert preview.picture.naturalWidth == 80
    assert preview.picture.naturalHeight == 40
    assert preview.picture.alt == "Generated landscape"
    assert preview.getAttribute("aria-busy") == "false"
    place_element(preview, 0, 5000, 240, 160)
    await expect_state(preview, "idle")
    assert preview.picture.getAttribute("src") is None
    assert preview._url == ""
    place_element(preview, 0, 0, 240, 160)
    await expect_state(preview, "ready")
    assert source.calls == 2
    preview.remove()
    assert preview._url == ""


@js
async def test_atomic_card_reordering_preserves_the_loaded_preview():
    source = ImageSource()
    preview = ImagePreview(alt="Moving card")
    preview.load_with(source.load)
    anchor = span("Another card")
    parent = div(anchor, preview)
    mount(parent)
    await expect_state(preview, "ready")
    url = preview.picture.src
    parent.moveBefore(preview, anchor)
    await wait_for_frames(3)
    assert source.calls == 1
    assert preview.get_data("state") == "ready"
    assert preview.picture.src == url


@js
async def test_stale_loader_does_not_publish_after_reconfiguration_or_disconnect():
    slow = ImageSource()
    slow.hold = True
    replacement = ImageSource()
    preview = ImagePreview(alt="Current image")
    preview.load_with(slow.load)
    mount(preview)
    for _ in range(120):
        if slow.calls:
            break
        await wait_for_frames(1)
    try:
        assert slow.calls == 1
        preview.load_with(replacement.load)
        await wait_for_frames(2)
        assert replacement.calls == 0
        assert preview.picture.getAttribute("src") is None
    finally:
        slow.hold = False
    await expect_state(preview, "ready")
    assert replacement.calls == 1
    slow.hold = True
    preview.load_with(slow.load)
    for _ in range(120):
        if slow.calls == 2:
            break
        await wait_for_frames(1)
    try:
        assert slow.calls == 2
        preview.remove()
    finally:
        slow.hold = False
    await wait_for_frames(4)
    assert preview._url == ""
    assert preview.picture.getAttribute("src") is None
    preview.load_with(replacement.load)
    mount(preview)
    await expect_state(preview, "ready")
    assert replacement.calls == 2


@js
async def test_bad_image_can_retry_without_triggering_the_parent_action():
    source = ImageSource()
    source.fail = True
    preview = ImagePreview(alt="Upload")
    preview.load_with(source.load)
    parent = div(preview)
    parent.setAttribute("data-clicked", "false")
    parent.addEventListener("click", lambda event: parent.setAttribute("data-clicked", "true"))
    mount(parent)
    await expect_state(preview, "error")
    assert preview.status.textContent == "Image unavailable"
    assert not preview.retry.hidden
    assert preview._url == ""
    source.fail = False
    preview.retry.click()
    await expect_state(preview, "ready")
    assert source.calls == 2
    assert parent.getAttribute("data-clicked") == "false"


@js
async def test_retry_does_not_follow_a_containing_card_link():
    source = ImageSource()
    source.fail = True
    preview = ImagePreview(alt="Linked image")
    preview.load_with(source.load)
    original = window.location.href
    destination = original.split("#")[0] + "#image-preview-card"
    parent = a({"href": destination, "style": "display:block;width:240px"}, preview)
    mount(parent)
    try:
        await expect_state(preview, "error")
        source.fail = False
        preview.retry.click()
        await expect_state(preview, "ready")
        await wait_for_frames(2)
        assert source.calls == 2
        assert window.location.href == original
        parent.click()
        await wait_for_frames(2)
        assert window.location.href == destination
    finally:
        window.history.replaceState(None, "", original)


@js
async def test_gallery_queue_skips_disconnected_work_before_reading_its_source():
    queue = ImagePreviewQueue()
    first_source = ImageSource()
    first_source.hold = True
    second_source = ImageSource()
    first = ImagePreview(alt="First")
    second = ImagePreview(alt="Second")
    first.load_with(first_source.load, queue=queue)
    second.load_with(second_source.load, queue=queue)
    parent = div({"style": "display:flex;width:400px"}, first)
    mount(parent)
    await expect_state(first, "loading")
    try:
        for _ in range(120):
            if first_source.calls:
                break
            await wait_for_frames(1)
        assert first_source.calls == 1
        parent.append(second)
        await expect_state(second, "loading")
        assert second_source.calls == 0
        second.remove()
    finally:
        first_source.hold = False
    await expect_state(first, "ready")
    await wait_for_frames(3)
    assert second_source.calls == 0
    assert second._url == ""
    parent.append(second)
    await expect_state(second, "ready")
    assert second_source.calls == 1


@js
async def test_hydrated_preview_accepts_a_client_loader_and_retries():
    preview = cast(ImagePreview, document.createElement("image-preview"))
    preview.set_data("self-id", "hydrated-image")
    preview.set_data("state", "idle")
    preview.set_data("max-width", "40")
    preview.set_data("max-height", "40")
    preview.setAttribute("style", "display:block;width:240px;aspect-ratio:1.5")
    preview.replaceChildren(
        img({"id": "hydrated-image-picture", "alt": "Restored image", "hidden": ""}),
        div({"id": "hydrated-image-placeholder"},
            span({"id": "hydrated-image-status"}, "Image preview"),
            button({"id": "hydrated-image-retry", "type": "button", "hidden": ""}, "Retry image")),
    )
    mount(preview)
    await wait_for_frames(3)
    source = ImageSource()
    source.fail = True
    preview.load_with(source.load)
    await expect_state(preview, "error")
    source.fail = False
    preview.retry.click()
    await expect_state(preview, "ready")
    assert preview.picture.naturalWidth == 40
    assert preview.picture.naturalHeight == 20
    assert preview.picture.alt == "Restored image"
