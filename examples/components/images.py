from pyjs import js
from pyjs.web.domx import div, p, ref, tw
from pyjs.web.files import Blob
from pyjs.web.html import OffscreenCanvas, OffscreenCanvasRenderingContext2D
from pyjs.web.ui import Widget
from pyjs.web.ui.image_preview import ImagePreview, ImagePreviewQueue


@js
async def sample_image() -> Blob:
    canvas = OffscreenCanvas(640, 360)
    context = canvas.getContext("2d")
    assert isinstance(context, OffscreenCanvasRenderingContext2D)
    context.fillStyle = "#d9e9e3"
    context.fillRect(0, 0, 640, 360)
    context.fillStyle = "#437a73"
    context.fillRect(48, 48, 240, 264)
    context.fillStyle = "#e2ad55"
    context.fillRect(320, 48, 272, 112)
    context.fillStyle = "#203f46"
    context.fillRect(320, 192, 272, 120)
    return await canvas.convertToBlob()


@js
class ImagePreviewExample(Widget):
    def __init__(self):
        super().__init__()
        self.contained = ref(ImagePreview(alt="Geometric color study", max_width=320))
        self.cropped = ref(ImagePreview(alt="Cropped color study", fit="cover", max_width=320))
        self.recovered = ref(ImagePreview(alt="Recoverable preview", max_width=320))
        self.add(tw("grid grid-cols-1 gap-6 sm:grid-cols-3"),
            div(self.contained, p(tw("mt-3 text-sm"), "Contain")),
            div(self.cropped, p(tw("mt-3 text-sm"), "Cover")),
            div(self.recovered, p(tw("mt-3 text-sm"), "Retry a failed load")),
        )

    def initialize(self):
        self.attempts = 0
        queue = ImagePreviewQueue()
        self.contained.load_with(sample_image, queue=queue)
        self.cropped.load_with(sample_image, queue=queue)
        self.recovered.load_with(self.load_recoverable, queue=queue)

    async def load_recoverable(self) -> Blob:
        self.attempts += 1
        if self.attempts == 1:
            return Blob(["unavailable image"], type="image/png")
        return await sample_image()
