import pytest

from pyjs import js
from pyjs.testing.webgpu import assert_webgpu_render, require_webgpu_adapter
from pyjs.web.dom import document
from pyjs.web.domx import canvas
from pyjs.web.webgpu import (
    Float32Array,
    GPUBufferDescriptor,
    GPUBufferUsage,
    GPUCanvasConfiguration,
    GPUColor,
    GPUColorTargetState,
    GPUDepthStencilState,
    GPUExtent3D,
    GPUFragmentState,
    GPUPrimitiveState,
    GPURenderPassColorAttachment,
    GPURenderPassDepthStencilAttachment,
    GPURenderPassDescriptor,
    GPURenderPipelineDescriptor,
    GPUShaderModuleDescriptor,
    GPUTextureDescriptor,
    GPUTextureUsage,
    GPUVertexAttribute,
    GPUVertexBufferLayout,
    GPUVertexState,
    Uint16Array,
    get_webgpu_context,
    navigator,
)


@pytest.mark.pyjs_web
@js
async def test_cube():
    cube_canvas = canvas()
    cube_canvas.width = 400
    cube_canvas.height = 400
    cube_canvas.setAttribute(
        "style",
        "display:block; width:400px; height:400px; margin:24px; border-radius:12px",
    )
    document.body.setAttribute("style", "margin:0; background:#111827")
    document.body.append(cube_canvas)

    adapter = await require_webgpu_adapter()
    device = await adapter.requestDevice()
    context = get_webgpu_context(cube_canvas)
    canvas_format = navigator.gpu.getPreferredCanvasFormat()
    context.configure(GPUCanvasConfiguration(device, canvas_format))

    vertex_values: list[float] = []
    vertex_values.extend([-1.0, -1.0, 1.0, 0.1, 0.4, 1.0])
    vertex_values.extend([1.0, -1.0, 1.0, 0.9, 0.2, 0.5])
    vertex_values.extend([1.0, 1.0, 1.0, 1.0, 0.7, 0.2])
    vertex_values.extend([-1.0, 1.0, 1.0, 0.2, 0.9, 0.5])
    vertex_values.extend([-1.0, -1.0, -1.0, 0.2, 0.3, 0.8])
    vertex_values.extend([1.0, -1.0, -1.0, 0.8, 0.2, 0.7])
    vertex_values.extend([1.0, 1.0, -1.0, 1.0, 0.6, 0.1])
    vertex_values.extend([-1.0, 1.0, -1.0, 0.1, 0.8, 0.8])
    vertices = Float32Array(vertex_values)

    index_values: list[int] = []
    index_values.extend([0, 1, 2, 0, 2, 3])
    index_values.extend([1, 5, 6, 1, 6, 2])
    index_values.extend([5, 4, 7, 5, 7, 6])
    index_values.extend([4, 0, 3, 4, 3, 7])
    index_values.extend([3, 2, 6, 3, 6, 7])
    index_values.extend([4, 5, 1, 4, 1, 0])
    indices = Uint16Array(index_values)
    vertex_buffer = device.createBuffer(
        GPUBufferDescriptor(
            vertices.byteLength,
            GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
        )
    )
    index_buffer = device.createBuffer(
        GPUBufferDescriptor(
            indices.byteLength,
            GPUBufferUsage.INDEX | GPUBufferUsage.COPY_DST,
        )
    )
    device.queue.writeBuffer(vertex_buffer, 0, vertices)
    device.queue.writeBuffer(index_buffer, 0, indices)

    shader = device.createShaderModule(
        GPUShaderModuleDescriptor(
            "struct VertexInput { @location(0) position: vec3f, "
            "@location(1) color: vec3f }; "
            "struct VertexOutput { @builtin(position) position: vec4f, "
            "@location(0) color: vec3f }; "
            "@vertex fn vertex_main(input: VertexInput) -> VertexOutput { "
            "let x = 0.76 * input.position.x + 0.65 * input.position.z; "
            "let z = -0.65 * input.position.x + 0.76 * input.position.z; "
            "let y = 0.84 * input.position.y - 0.54 * z; "
            "let depth = 0.54 * input.position.y + 0.84 * z; "
            "var output: VertexOutput; "
            "output.position = vec4f(0.46 * x, 0.46 * y, 0.12 * depth + 0.5, 1.0); "
            "output.color = input.color; return output; } "
            "@fragment fn fragment_main(input: VertexOutput) -> @location(0) vec4f { "
            "return vec4f(input.color, 1.0); }"
        )
    )
    pipeline = await device.createRenderPipelineAsync(
        GPURenderPipelineDescriptor(
            GPUVertexState(
                shader,
                "vertex_main",
                [
                    GPUVertexBufferLayout(
                        24,
                        [
                            GPUVertexAttribute("float32x3", 0, 0),
                            GPUVertexAttribute("float32x3", 12, 1),
                        ],
                    )
                ],
            ),
            GPUFragmentState(
                shader,
                "fragment_main",
                [GPUColorTargetState(canvas_format)],
            ),
            GPUPrimitiveState(),
            GPUDepthStencilState(),
        )
    )
    depth_texture = device.createTexture(
        GPUTextureDescriptor(
            GPUExtent3D(cube_canvas.width, cube_canvas.height),
            "depth24plus",
            GPUTextureUsage.RENDER_ATTACHMENT,
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
            GPURenderPassDepthStencilAttachment(depth_texture.createView()),
        )
    )
    render_pass.setPipeline(pipeline)
    render_pass.setVertexBuffer(0, vertex_buffer)
    render_pass.setIndexBuffer(index_buffer, "uint16")
    render_pass.drawIndexed(indices.length)
    render_pass.end()
    device.queue.submit([encoder.finish()])

    await assert_webgpu_render(device, cube_canvas, "cube")
