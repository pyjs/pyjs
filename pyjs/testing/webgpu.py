"""Browser render assertions for WebGPU tests."""

from pyjs import js
from pyjs.testing.client.runtime import window
from pyjs.testing.client.state import RenderArtifact
from pyjs.web.html import HTMLCanvasElement
from pyjs.web.webgpu import GPUAdapter, GPUDevice, navigator


@js
async def require_webgpu_adapter() -> GPUAdapter:
    """Acquire WebGPU or raise an error distinct from a render mismatch."""
    if navigator.gpu is None:
        raise RuntimeError("WebGPU API is unavailable in this browser")
    adapter = await navigator.gpu.requestAdapter()
    if adapter is None:
        raise RuntimeError(
            "WebGPU adapter acquisition failed: requestAdapter() returned None"
        )
    return adapter


@js
def webgpu_render_diagnostics(device: GPUDevice, canvas: HTMLCanvasElement) -> str:
    info = device.adapterInfo
    if info is None:
        return "adapter information unavailable; canvas=" + str(canvas.width) + "x" + str(
            canvas.height
        )
    return (
        "vendor="
        + info.vendor
        + "; architecture="
        + info.architecture
        + "; device="
        + info.device
        + "; description="
        + info.description
        + "; fallback="
        + str(info.isFallbackAdapter)
        + "; canvas="
        + str(canvas.width)
        + "x"
        + str(canvas.height)
    )


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
            diagnostics=webgpu_render_diagnostics(device, canvas),
        )
    )
