from pyjs.testing.webgpu import webgpu_render_diagnostics
from pyjs.web.domx import canvas
from pyjs.web.webgpu import GPUAdapterInfo, GPUDevice


def test_webgpu_diagnostics_cover_missing_adapter_information():
    target = canvas()
    target.width = 320
    target.height = 200

    assert webgpu_render_diagnostics(GPUDevice(), target) == (
        "adapter information unavailable; canvas=320x200"
    )


def test_webgpu_diagnostics_describe_the_adapter_and_canvas():
    target = canvas()
    target.width = 400
    target.height = 300
    info = GPUAdapterInfo()
    info.vendor = "Example"
    info.architecture = "software"
    info.device = "Renderer"
    info.description = "Test adapter"
    info.isFallbackAdapter = True
    device = GPUDevice()
    device.adapterInfo = info

    assert webgpu_render_diagnostics(device, target) == (
        "vendor=Example; architecture=software; device=Renderer; "
        "description=Test adapter; fallback=True; canvas=400x300"
    )
