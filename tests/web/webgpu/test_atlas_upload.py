from typing import Final

import pytest

from pyjs import JS, js
from pyjs.javascript import Float32Array
from pyjs.testing.webgpu import assert_webgpu_render, require_webgpu_adapter
from pyjs.web.dom import document
from pyjs.web.domx import canvas
from pyjs.web.html import (
    CanvasRenderingContext2DSettings,
    OffscreenCanvas,
    get_offscreen_2d_context,
)
from pyjs.web.webgpu import (
    GPUBindGroupDescriptor,
    GPUBindGroupEntry,
    GPUCanvasConfiguration,
    GPUColor,
    GPUColorTargetState,
    GPUCopyExternalImageDestInfo,
    GPUCopyExternalImageSourceInfo,
    GPUExtent3D,
    GPUFragmentState,
    GPUPrimitiveState,
    GPURenderPassColorAttachment,
    GPURenderPassDescriptor,
    GPURenderPipelineDescriptor,
    GPUShaderModuleDescriptor,
    GPUTextureDescriptor,
    GPUTextureUsage,
    GPUVertexState,
    get_webgpu_context,
    navigator,
)

ATLAS_SIZE: Final[JS] = 64


@pytest.mark.pyjs_web
@js
async def test_offscreen_glyph_uploads_through_copy_external_image_to_texture():
    glyph_canvas = canvas()
    glyph_canvas.width = ATLAS_SIZE
    glyph_canvas.height = ATLAS_SIZE
    glyph_canvas.setAttribute(
        "style",
        "display:block; width:64px; height:64px; margin:24px; image-rendering:pixelated",
    )
    document.body.setAttribute("style", "margin:0; background:#111827")
    document.body.append(glyph_canvas)

    offscreen = OffscreenCanvas(ATLAS_SIZE, ATLAS_SIZE)
    context_2d = get_offscreen_2d_context(
        offscreen,
        CanvasRenderingContext2DSettings(alpha=True, willReadFrequently=True),
    )
    if context_2d is None:
        raise RuntimeError("OffscreenCanvas 2d context is unavailable")
    context_2d.fillStyle = "#112244"
    context_2d.fillRect(0, 0, ATLAS_SIZE, ATLAS_SIZE)
    context_2d.fillStyle = "#f4f4f5"
    context_2d.font = "48px sans-serif"
    context_2d.textBaseline = "top"
    context_2d.fillText("A", 10, 6)

    adapter = await require_webgpu_adapter()
    device = await adapter.requestDevice()
    context = get_webgpu_context(glyph_canvas)
    canvas_format = navigator.gpu.getPreferredCanvasFormat()
    context.configure(GPUCanvasConfiguration(device, canvas_format))

    usage = GPUTextureUsage
    atlas = device.createTexture(
        GPUTextureDescriptor(
            GPUExtent3D(ATLAS_SIZE, ATLAS_SIZE),
            "rgba8unorm",
            usage.TEXTURE_BINDING | usage.COPY_DST | usage.RENDER_ATTACHMENT,
            label="glyph-atlas",
        )
    )
    element_size = Float32Array.BYTES_PER_ELEMENT
    if element_size != 4:
        raise RuntimeError("Float32Array.BYTES_PER_ELEMENT must be 4")
    device.queue.copyExternalImageToTexture(
        GPUCopyExternalImageSourceInfo(offscreen),
        GPUCopyExternalImageDestInfo(atlas),
        width=ATLAS_SIZE,
        height=ATLAS_SIZE,
    )

    shader = device.createShaderModule(
        GPUShaderModuleDescriptor(
            "struct Out { @builtin(position) clip: vec4f, @location(0) uv: vec2f }; "
            "@group(0) @binding(0) var tex: texture_2d<f32>; "
            "@group(0) @binding(1) var samp: sampler; "
            "@vertex fn vs(@builtin(vertex_index) i: u32) -> Out { "
            "let p = array<vec2f, 3>(vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0)); "
            "var o: Out; o.clip = vec4f(p[i], 0.0, 1.0); "
            "o.uv = vec2f(p[i].x * 0.5 + 0.5, 0.5 - p[i].y * 0.5); return o; } "
            "@fragment fn fs(o: Out) -> @location(0) vec4f { "
            "return textureSample(tex, samp, o.uv); }"
        )
    )
    pipeline = await device.createRenderPipelineAsync(
        GPURenderPipelineDescriptor(
            GPUVertexState(shader, "vs", []),
            GPUFragmentState(shader, "fs", [GPUColorTargetState(canvas_format)]),
            GPUPrimitiveState(cull_mode="none"),
            None,
        )
    )
    sampler = device.createSampler(magFilter="nearest", minFilter="nearest")
    bind_group = device.createBindGroup(
        GPUBindGroupDescriptor(
            pipeline.getBindGroupLayout(0),
            [
                GPUBindGroupEntry(0, atlas.createView()),
                GPUBindGroupEntry(1, sampler),
            ],
        )
    )
    encoder = device.createCommandEncoder()
    render_pass = encoder.beginRenderPass(
        GPURenderPassDescriptor(
            [
                GPURenderPassColorAttachment(
                    context.getCurrentTexture().createView(),
                    GPUColor(0.04, 0.06, 0.11),
                )
            ],
            None,
        )
    )
    render_pass.setPipeline(pipeline)
    render_pass.setBindGroup(0, bind_group)
    render_pass.draw(3)
    render_pass.end()
    device.queue.submit([encoder.finish()])

    await assert_webgpu_render(device, glyph_canvas, "atlas_glyph")
