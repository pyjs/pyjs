"""Viewport-loaded, bounded still-image previews with owned browser resources."""

from collections.abc import Awaitable, Callable
from math import isfinite
from typing import cast

from pyjs import js, llvm
from pyjs.web.async_lock import AsyncLock
from pyjs.web.dom import (
    IntersectionObserver,
    IntersectionObserverEntry,
    IntersectionObserverInit,
)
from pyjs.web.domx import img, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.files import Blob
from pyjs.web.html import (
    HTMLButtonElement,
    OffscreenCanvas,
    OffscreenCanvasRenderingContext2D,
    createImageBitmap,
)
from pyjs.web.timers import queueMicrotask
from pyjs.web.ui import Widget
from pyjs.web.ui.button import Button
from pyjs.web.url import URL

type ImageLoader = Callable[[], Awaitable[Blob]]

@js
class ImagePreviewQueue:
    """Share one queue across a gallery to bound concurrent reads and decoding."""

    def __init__(self):
        self.lock = AsyncLock()


@js
async def _preview_blob(source: Blob, max_width: int, max_height: int) -> Blob:
    bitmap = await createImageBitmap(source)
    try:
        scale = min(1.0, max_width / bitmap.width, max_height / bitmap.height)
        width = max(1, int(bitmap.width * scale))
        height = max(1, int(bitmap.height * scale))
        canvas = OffscreenCanvas(width, height)
        context = canvas.getContext("2d")
        if not isinstance(context, OffscreenCanvasRenderingContext2D):
            raise RuntimeError("Image preview rendering is unavailable")
        context.scale(width / bitmap.width, height / bitmap.height)
        context.drawImage(bitmap, 0, 0)
        return await canvas.convertToBlob(type="image/png")
    finally:
        bitmap.close()


@js
class ImagePreview(Widget):
    """Load a Blob in the viewport and display a bounded still-frame preview.

    Register a client-side ``load_with`` callback before or after mounting.
    Pass a shared ImagePreviewQueue to ``load_with`` to serialize reads and
    decoding. Leaving the viewport releases the displayed blob; returning
    loads it again. The callback owns validation and cancellation/timeouts
    of its external I/O.
    Decoding temporarily needs the original image's pixels. Animated inputs
    display a still frame; originals are neither modified nor retained here.
    """

    _loader: ImageLoader | None = None

    def __init__(self, *, alt: str, ratio: float = 1.5, fit: str = "contain",
                 max_width: int = 960, max_height: int = 640):
        super().__init__()
        self._queue: ImagePreviewQueue | None = None
        if not isfinite(ratio) or ratio <= 0 or max_width < 1 or max_height < 1:
            raise ValueError("Image preview dimensions must be positive")
        if fit not in ["contain", "cover"]:
            raise ValueError("Image preview fit must be contain or cover")
        self.picture = ref(img(tw(
            "size-full object-contain group-data-[fit=cover]/image-preview:object-cover"
        ), {"alt": alt, "decoding": "async", "hidden": "", "data-slot": "image-preview-image"}))
        self.status = ref(tag("span", {"role": "status"}, "Image preview"))
        retry = Button("Retry image", variant="outline", size="sm")
        self.retry = ref(cast(HTMLButtonElement, retry.element))
        self.retry.setAttribute("hidden", "")
        self.retry.setAttribute("aria-label", "Retry loading image")
        self.placeholder = ref(tag("div", tw(
            "absolute inset-0 flex flex-col items-center justify-center gap-2 p-3 text-center "
            "text-sm text-slate-500"
        ), self.status, self.retry))
        self.add(tw("group/image-preview relative block w-full overflow-hidden rounded-lg bg-slate-100"),
                 {"data-slot": "image-preview", "data-state": "idle", "data-fit": fit,
                  "data-max-width": str(max_width), "data-max-height": str(max_height),
                  "style": "aspect-ratio: " + str(ratio)}, self.picture, self.placeholder)

    def initialize(self):
        self.retry.addEventListener("click", self.retry_load)
        if self._queue is None:
            self._queue = ImagePreviewQueue()
        self._generation = 0
        self._url = ""
        self._visible = False
        self._observer: IntersectionObserver | None = None
        self.reconnected()

    def reconnected(self):
        if self._observer is None:
            observer = IntersectionObserver(self.intersected, IntersectionObserverInit())
            observer.observe(self)
            self._observer = observer

    def disconnected(self):
        if self._observer is not None:
            self._observer.disconnect()
            self._observer = None
        self._visible = False
        self.release()

    @llvm.inline("")
    def load_with(self, loader: ImageLoader, *, queue: ImagePreviewQueue | None = None):
        self._loader = loader
        if queue is not None:
            self._queue = queue
        if self._initialized:
            self.release()
            if self._visible:
                queueMicrotask(self.load)

    def release(self):
        self._generation += 1
        self.picture.removeAttribute("src")
        self.picture.hidden = True
        if self._url:
            URL.revokeObjectURL(self._url)
            self._url = ""
        self.set_data("state", "idle")
        self.setAttribute("aria-busy", "false")
        self.placeholder.hidden = False
        self.status.textContent = "Image preview"
        self.retry.hidden = True

    async def intersected(self, entries: list[IntersectionObserverEntry], observer: IntersectionObserver):
        if observer is not self._observer:
            return
        for entry in entries:
            self._visible = entry.isIntersecting
        if self._visible:
            if self.get_data("state") == "idle":
                await self.load()
        else:
            self.release()

    async def retry_load(self, event: Event):
        event.stopPropagation()
        await self.load()

    async def load(self):
        loader = self._loader
        queue = self._queue
        if loader is None or queue is None or not self.isConnected or not self._visible:
            return
        self.release()
        generation = self._generation
        self.set_data("state", "loading")
        self.setAttribute("aria-busy", "true")
        self.status.textContent = "Loading image…"
        await queue.lock.acquire()
        try:
            if generation != self._generation:
                return
            source = await loader()
            if generation != self._generation:
                return
            thumbnail = await _preview_blob(source, int(self.get_data("max-width") or "960"),
                                             int(self.get_data("max-height") or "640"))
            if generation != self._generation:
                return
            self._url = URL.createObjectURL(thumbnail)
            self.picture.src = self._url
            await self.picture.decode()
            if generation != self._generation:
                return
            self.picture.hidden = False
            self.placeholder.hidden = True
            self.set_data("state", "ready")
            self.setAttribute("aria-busy", "false")
        except Exception:
            if generation == self._generation:
                self.release()
                self.set_data("state", "error")
                self.status.textContent = "Image unavailable"
                self.retry.hidden = False
        finally:
            queue.lock.release()
