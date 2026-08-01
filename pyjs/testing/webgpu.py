"""Browser render assertions for WebGPU tests."""

from pyjs import js
from pyjs.testing.client.runtime import window
from pyjs.testing.client.state import RenderArtifact
from pyjs.web.html import HTMLCanvasElement
from pyjs.web.webgpu import GPUDevice


@js
async def assert_webgpu_render(
    device: GPUDevice,
    canvas: HTMLCanvasElement,
    name: str,
    pixel_threshold: int = 8,
    max_different_pixel_ratio: float = 0.01,
):
    """Capture a completed WebGPU frame for comparison by the pytest runner."""
    await device.queue.onSubmittedWorkDone()
    window.__pyjsRenderArtifacts__.append(
        RenderArtifact(
            name,
            canvas.toDataURL("image/png"),
            pixel_threshold,
            max_different_pixel_ratio,
        )
    )
