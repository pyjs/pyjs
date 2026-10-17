import asyncio
import struct

import pytest

from pyjs.javascript import (
    ArrayBuffer,
    BigUint64Array,
    DataView,
    Float16Array,
    Float32Array,
    Float64Array,
    Int8Array,
    Uint8Array,
    Uint8ClampedArray,
    Uint32Array,
    typed_array_bytes,
)
from pyjs.shader.transpiler import transpile_wgsl
from pyjs.web import webgpu as W
from pyjs.web._webgpu import buffer_source_bytes, lower


def test_typed_arrays_hold_bytes_natively():
    values = Float32Array([1.5, -2.0, 3.0])
    assert values.length == 3
    assert values.byteLength == 12
    assert values.BYTES_PER_ELEMENT == 4
    assert Float32Array.BYTES_PER_ELEMENT == 4
    assert struct.unpack("<3f", typed_array_bytes(values)) == (1.5, -2.0, 3.0)

    zeros = Uint32Array(4)
    assert zeros.length == 4 and zeros.byteLength == 16
    assert Uint32Array.BYTES_PER_ELEMENT == 4
    assert Uint8Array.BYTES_PER_ELEMENT == 1
    assert Float64Array.BYTES_PER_ELEMENT == 8

    view = Float32Array(ArrayBuffer(8))
    assert view.length == 2


def test_typed_array_views_share_storage_and_slices_copy():
    buffer = ArrayBuffer(16)
    view = Uint32Array(buffer, 4, 2)
    assert view.byteOffset == 4 and view.byteLength == 8 and view.length == 2
    view[0] = 0x12345678
    view[1] = -1
    assert typed_array_bytes(view) == bytes.fromhex("78563412ffffffff")

    shared = view.subarray(1)
    copied = view.slice(1)
    shared[0] = 7
    assert view[1] == 7
    assert copied[0] == 0xFFFFFFFF

    view.set(view.subarray(0, 1), 1)
    assert view[1] == view[0]
    assert ArrayBuffer.isView(view) and ArrayBuffer.isView(DataView(buffer))


def test_typed_array_values_use_javascript_coercion_rules():
    assert list(Uint8Array([-1, 256, 257])) == [255, 0, 1]
    assert list(Int8Array([128, 255])) == [-128, -1]
    assert list(Uint8ClampedArray([-1, 0.5, 1.5, 254.5, 300, float("nan")])) \
        == [0, 0, 2, 254, 255, 0]
    assert Float16Array([1e100])[0] == float("inf")
    assert tuple(BigUint64Array([2**63 + 17])) == (2**63 + 17,)


def test_typed_array_view_ranges_are_validated():
    buffer = ArrayBuffer(10)
    with pytest.raises(ValueError, match="aligned"):
        Uint32Array(buffer, 1)
    with pytest.raises(ValueError, match="outside"):
        Uint32Array(buffer, 4, 2)
    with pytest.raises(ValueError, match="outside"):
        DataView(buffer, 11)


def test_buffer_source_offsets_count_typed_elements():
    values = Uint32Array([10, 20, 30])
    assert buffer_source_bytes(values, 1, 1) == struct.pack("<I", 20)


def test_descriptors_lower_to_wgpu_arguments():
    layout = W.GPUBindGroupLayoutDescriptor(
        [W.GPUBindGroupLayoutEntry(1, W.GPUShaderStage.COMPUTE,
                                   buffer=W.GPUBufferBindingLayout(type="storage"))],
        label="lattice",
    )
    lowered = lower(layout)
    assert lowered["label"] == "lattice"
    assert lowered["entries"][0]["binding"] == 1
    assert lowered["entries"][0]["buffer"] == {"has_dynamic_offset": False,
                                               "min_binding_size": 0, "type": "storage"}


def test_adapter_options_are_forwarded_to_wgpu(monkeypatch):
    calls = []

    class NativeAdapter:
        info = {"vendor": "test", "adapter_type": "CPU"}
        features = {"feature-a"}
        limits = {"limit-a": 1}

    def request(feature_level, power_preference, fallback):
        calls.append((feature_level, power_preference, fallback))
        return NativeAdapter()

    monkeypatch.setattr(W, "request_adapter", request)
    adapter = asyncio.run(W.GPU().requestAdapter(
        featureLevel="compatibility",
        powerPreference="low-power",
        forceFallbackAdapter=True,
        xrCompatible=True,
    ))
    assert calls == [("compatibility", "low-power", True)]
    assert adapter.info.vendor == "test" and adapter.info.isFallbackAdapter


def test_device_options_are_forwarded_to_wgpu():
    calls = []

    class NativeDevice:
        queue = object()
        features = {"feature-a"}
        limits = {"limit-a": 1}

    class NativeAdapter:
        def request_device_sync(self, **kwargs):
            calls.append(kwargs)
            return NativeDevice()

    adapter = W.GPUAdapter()
    adapter._native = NativeAdapter()
    adapter.info = W.GPUAdapterInfo()
    queue = W.GPUQueueDescriptor("commands")
    device = asyncio.run(adapter.requestDevice(
        label="device",
        requiredFeatures=["feature-a"],
        requiredLimits={"limit-a": 1},
        defaultQueue=queue,
    ))
    assert calls == [{
        "label": "device",
        "required_features": ["feature-a"],
        "required_limits": {"limit-a": 1},
        "default_queue": {"label": "commands"},
    }]
    assert device.label == "device" and device.queue._native is NativeDevice.queue


def test_pass_offsets_and_unbound_vertex_buffers_are_forwarded():
    class NativePass:
        def __init__(self):
            self.calls = []

        def set_bind_group(self, *args):
            self.calls.append(("bind", args))

        def set_vertex_buffer(self, *args):
            self.calls.append(("vertex", args))

    bind_group = W.GPUBindGroup()
    bind_group._native = "bind-group"

    compute = W.GPUComputePassEncoder()
    compute._native = NativePass()
    compute.setBindGroup(2, bind_group, [4, 8])
    assert compute._native.calls == [("bind", (2, "bind-group", [4, 8]))]

    render = W.GPURenderPassEncoder()
    render._native = NativePass()
    render.setVertexBuffer(1, None, 16, None)
    assert render._native.calls == [("vertex", (1, None, 16, None))]


def test_texture_view_forwards_every_view_option():
    calls = []

    class NativeTexture:
        def create_view(self, **kwargs):
            calls.append(kwargs)
            return object()

    texture = W.GPUTexture()
    texture._native = NativeTexture()
    view = texture.createView(
        label="albedo",
        format="rgba8unorm",
        dimension="2d-array",
        usage=W.GPUTextureUsage.TEXTURE_BINDING,
        aspect="all",
        baseMipLevel=2,
        mipLevelCount=3,
        baseArrayLayer=4,
        arrayLayerCount=5,
        swizzle="bgra",
    )

    assert view.label == "albedo"
    assert calls == [{
        "label": "albedo",
        "format": "rgba8unorm",
        "dimension": "2d-array",
        "usage": W.GPUTextureUsage.TEXTURE_BINDING,
        "aspect": "all",
        "base_mip_level": 2,
        "mip_level_count": 3,
        "base_array_layer": 4,
        "array_layer_count": 5,
        "swizzle": "bgra",
    }]


def test_pipeline_and_bind_group_labels_reach_native_objects():
    calls = []

    class NativeDevice:
        def create_bind_group_layout(self, **kwargs):
            calls.append(("empty-layout", kwargs))
            return "empty-layout"

        def create_pipeline_layout(self, **kwargs):
            calls.append(("layout", kwargs))
            return object()

        def create_compute_pipeline(self, **kwargs):
            calls.append(("compute", kwargs))
            return object()

        def create_bind_group(self, **kwargs):
            calls.append(("bind", kwargs))
            return object()

    device = W.GPUDevice()
    device._native = NativeDevice()
    group_layout = W.GPUBindGroupLayout()
    group_layout._native = "group-layout"
    pipeline_layout = device.createPipelineLayout(
        W.GPUPipelineLayoutDescriptor(
            [group_layout, None],
            immediateSize=16,
            label="pipeline-layout",
        )
    )
    module = W.GPUShaderModule()
    module._native = "shader"
    pipeline = device.createComputePipeline(
        W.GPUComputePipelineDescriptor(
            W.GPUProgrammableStage(module, entryPoint="main"),
            pipeline_layout,
            label="compute-pipeline",
        )
    )
    bind_group = device.createBindGroup(
        W.GPUBindGroupDescriptor(group_layout, [], label="resources")
    )

    assert pipeline_layout.label == "pipeline-layout"
    assert pipeline.label == "compute-pipeline"
    assert bind_group.label == "resources"
    assert calls == [
        ("empty-layout", {"entries": []}),
        (
            "layout",
            {
                "label": "pipeline-layout",
                "bind_group_layouts": ["group-layout", "empty-layout"],
                "immediate_size": 16,
            },
        ),
        (
            "compute",
            {
                "label": "compute-pipeline",
                "layout": pipeline_layout._native,
                "compute": {
                    "module": "shader",
                    "constants": {},
                    "entry_point": "main",
                },
            },
        ),
        (
            "bind",
            {
                "label": "resources",
                "layout": "group-layout",
                "entries": [],
            },
        ),
    ]


def test_pipeline_bind_group_layouts_wrap_native_results():
    calls = []

    class NativeLayout:
        label = "inferred-layout"

    native_layout = NativeLayout()

    class NativePipeline:
        def get_bind_group_layout(self, index):
            calls.append(index)
            return native_layout

    for pipeline_type in (W.GPUComputePipeline, W.GPURenderPipeline):
        pipeline = pipeline_type()
        pipeline._native = NativePipeline()
        layout = pipeline.getBindGroupLayout(2)
        assert isinstance(layout, W.GPUBindGroupLayout)
        assert layout._native is native_layout
        assert layout.label == "inferred-layout"

    assert calls == [2, 2]


def test_explicit_zero_buffer_binding_size_is_not_replaced():
    calls = []

    class NativeDevice:
        def create_bind_group(self, **kwargs):
            calls.append(kwargs)
            return object()

    device = W.GPUDevice()
    device._native = NativeDevice()
    layout = W.GPUBindGroupLayout()
    layout._native = "layout"
    buffer = W.GPUBuffer()
    buffer._native = "buffer"
    buffer.size = 64
    binding = W.GPUBufferBinding(buffer, offset=16, size=0)

    device.createBindGroup(
        W.GPUBindGroupDescriptor(
            layout,
            [W.GPUBindGroupEntry(0, binding)],
        )
    )

    assert calls == [{
        "label": "",
        "layout": "layout",
        "entries": [{
            "binding": 0,
            "resource": {"buffer": "buffer", "offset": 16, "size": 0},
        }],
    }]


def test_created_native_wrappers_retain_their_public_labels():
    class NativeEncoder:
        def begin_render_pass(self, **kwargs):
            return object()

        def finish(self, **kwargs):
            return object()

    class NativeDevice:
        def create_bind_group_layout(self, **kwargs):
            return object()

        def create_shader_module(self, **kwargs):
            return object()

        def create_command_encoder(self, **kwargs):
            return NativeEncoder()

    device = W.GPUDevice()
    device._native = NativeDevice()
    layout = device.createBindGroupLayout(
        W.GPUBindGroupLayoutDescriptor([], label="bindings")
    )
    shader = device.createShaderModule(
        W.GPUShaderModuleDescriptor("@compute fn main() {}", label="shader")
    )
    encoder = device.createCommandEncoder(label="commands")
    render_pass = encoder.beginRenderPass(
        W.GPURenderPassDescriptor([], None, label="render")
    )
    commands = encoder.finish(label="finished")

    assert (
        layout.label,
        shader.label,
        encoder.label,
        render_pass.label,
        commands.label,
    ) == ("bindings", "shader", "commands", "render", "finished")


def _adapter():
    try:
        return asyncio.run(W.navigator.gpu.requestAdapter())
    except Exception as error:  # no adapter on this machine
        pytest.skip(f"no WebGPU adapter: {error}")


def test_compute_roundtrip_through_the_spec_surface():
    adapter = _adapter()

    async def run():
        device = await adapter.requestDevice()
        usage = W.GPUBufferUsage
        count = 64
        source = Float32Array([float(i) for i in range(count)])
        inp = device.createBuffer(W.GPUBufferDescriptor(source.byteLength, usage.STORAGE | usage.COPY_DST))
        out = device.createBuffer(W.GPUBufferDescriptor(source.byteLength, usage.STORAGE | usage.COPY_SRC))
        read = device.createBuffer(W.GPUBufferDescriptor(source.byteLength, usage.MAP_READ | usage.COPY_DST))
        device.queue.writeBuffer(inp, 0, source)
        module = device.createShaderModule(W.GPUShaderModuleDescriptor("""
            @group(0) @binding(0) var<storage, read> inp: array<f32>;
            @group(0) @binding(1) var<storage, read_write> out: array<f32>;
            @compute @workgroup_size(64)
            fn main(@builtin(global_invocation_id) id: vec3<u32>) {
              out[id.x] = inp[id.x] * 2.0 + 1.0;
            }"""))
        layout = device.createBindGroupLayout(W.GPUBindGroupLayoutDescriptor([
            W.GPUBindGroupLayoutEntry(0, W.GPUShaderStage.COMPUTE,
                                      buffer=W.GPUBufferBindingLayout(type="read-only-storage")),
            W.GPUBindGroupLayoutEntry(1, W.GPUShaderStage.COMPUTE,
                                      buffer=W.GPUBufferBindingLayout(type="storage"))]))
        pipeline = device.createComputePipeline(W.GPUComputePipelineDescriptor(
            W.GPUProgrammableStage(module, entryPoint="main"),
            device.createPipelineLayout(W.GPUPipelineLayoutDescriptor([layout]))))
        bind = device.createBindGroup(W.GPUBindGroupDescriptor(layout, [
            W.GPUBindGroupEntry(0, W.GPUBufferBinding(inp)),
            W.GPUBindGroupEntry(1, W.GPUBufferBinding(out))]))
        encoder = device.createCommandEncoder()
        cpass = encoder.beginComputePass()
        cpass.setPipeline(pipeline)
        cpass.setBindGroup(0, bind)
        cpass.dispatchWorkgroups(1)
        cpass.end()
        encoder.copyBufferToBuffer(out, read, source.byteLength)
        device.queue.submit([encoder.finish()])
        await read.mapAsync(W.GPUMapMode.READ)
        result = struct.unpack(f"<{count}f", bytes(read.getMappedRange()._bytes))
        read.unmap()
        assert read.mapState == "unmapped"
        return result

    result = asyncio.run(run())
    assert result == tuple(float(i) * 2.0 + 1.0 for i in range(64))


def test_generated_arrays_modulo_and_descending_ranges_compile_as_wgsl():
    adapter = _adapter()
    library = transpile_wgsl("""
from dataclasses import dataclass
from pyjs import wgsl
from pyjs.shader import Array, f32, i32, vec3f

@wgsl
@dataclass
class Point:
    position: vec3f
    weight: f32

@wgsl
def total(items: Array[f32, 4]) -> f32:
    result = 0.0
    for i in range(4):
        result = result + items[i]
    return result

@wgsl
def integer_mod(left: i32, right: i32) -> i32:
    return left % right

@wgsl
def float_mod(left: f32, right: f32) -> f32:
    return left % right

@wgsl
def descending_total() -> i32:
    result = 0
    for i in range(3, 0, -1):
        result = result + i
    return result

@wgsl
def snapshotted_total(stop: i32) -> i32:
    result = 0
    bound = stop
    for i in range(bound):
        result += i
        bound = 0
    return result

@wgsl
def equal_points(left: Point, right: Point) -> bool:
    return left == right
""")
    source = library + """
@compute @workgroup_size(1)
fn main() {
  let array_result = total(array<f32, 4>(1.0, 2.0, 3.0, 4.0));
  let integer_result = integer_mod(-7, 3) + descending_total()
      + snapshotted_total(4);
  let float_result = float_mod(-7.0, 3.0);
  let points_equal = equal_points(
      Point(vec3f(1.0, 2.0, 3.0), 4.0),
      Point(vec3f(1.0, 2.0, 3.0), 4.0));
}
"""

    async def compile_shader():
        device = await adapter.requestDevice()
        module = device.createShaderModule(W.GPUShaderModuleDescriptor(source))
        device.createComputePipeline(W.GPUComputePipelineDescriptor(
            W.GPUProgrammableStage(module, entryPoint="main"), "auto"))

    asyncio.run(compile_shader())


def test_nullable_pipeline_layout_slot_reaches_wgpu_py():
    adapter = _adapter()

    async def create_pipeline():
        device = await adapter.requestDevice()
        module = device.createShaderModule(W.GPUShaderModuleDescriptor("""
            @group(1) @binding(0) var<storage, read> values: array<u32>;

            @compute @workgroup_size(1)
            fn main() {
              let first = values[0];
            }
        """))
        group_one = device.createBindGroupLayout(
            W.GPUBindGroupLayoutDescriptor([
                W.GPUBindGroupLayoutEntry(
                    0,
                    W.GPUShaderStage.COMPUTE,
                    buffer=W.GPUBufferBindingLayout(type="read-only-storage"),
                ),
            ])
        )
        pipeline_layout = device.createPipelineLayout(
            W.GPUPipelineLayoutDescriptor([None, group_one])
        )
        device.createComputePipeline(
            W.GPUComputePipelineDescriptor(
                W.GPUProgrammableStage(module, entryPoint="main"),
                pipeline_layout,
            )
        )

    asyncio.run(create_pipeline())


@pytest.mark.parametrize("mapped_at_creation", [False, True])
def test_writable_mapping_reaches_the_gpu_buffer(mapped_at_creation: bool):
    adapter = _adapter()

    async def run():
        device = await adapter.requestDevice()
        usage = W.GPUBufferUsage
        if mapped_at_creation:
            write = device.createBuffer(W.GPUBufferDescriptor(
                16, usage.COPY_SRC, mapped_at_creation=True))
        else:
            write = device.createBuffer(W.GPUBufferDescriptor(
                16, usage.MAP_WRITE | usage.COPY_SRC))
            await write.mapAsync(W.GPUMapMode.WRITE)
        mapped = Uint32Array(write.getMappedRange())
        mapped.set([11, 22, 33, 44])
        write.unmap()

        read = device.createBuffer(W.GPUBufferDescriptor(
            16, usage.MAP_READ | usage.COPY_DST))
        encoder = device.createCommandEncoder()
        encoder.copyBufferToBuffer(write, read, 16)
        device.queue.submit([encoder.finish()])
        await read.mapAsync(W.GPUMapMode.READ)
        result = tuple(Uint32Array(read.getMappedRange()))
        read.unmap()
        return result

    assert asyncio.run(run()) == (11, 22, 33, 44)


def test_submitted_work_done_forwards_the_native_promise():
    class NativeQueue:
        def __init__(self):
            self.awaited = False

        async def on_submitted_work_done_async(self):
            self.awaited = True

    queue = W.GPUQueue()
    queue._native = NativeQueue()
    asyncio.run(queue.onSubmittedWorkDone())
    assert queue._native.awaited


def test_render_pass_draws_into_a_texture():
    adapter = _adapter()

    async def run():
        device = await adapter.requestDevice()
        width = height = 8
        texture = device.createTexture(W.GPUTextureDescriptor(
            [width, height], "rgba8unorm",
            W.GPUTextureUsage.RENDER_ATTACHMENT | W.GPUTextureUsage.COPY_SRC))
        module = device.createShaderModule(W.GPUShaderModuleDescriptor("""
            @vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
              let p = array<vec2<f32>, 3>(vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
              return vec4<f32>(p[i], 0.0, 1.0);
            }
            @fragment fn fs() -> @location(0) vec4<f32> { return vec4<f32>(1.0, 0.5, 0.0, 1.0); }"""))
        pipeline = device.createRenderPipeline(W.GPURenderPipelineDescriptor(
            W.GPUVertexState(module, "vs", []),
            W.GPUFragmentState(module, "fs", [W.GPUColorTargetState("rgba8unorm")]),
            W.GPUPrimitiveState(), None))
        encoder = device.createCommandEncoder()
        rpass = encoder.beginRenderPass(W.GPURenderPassDescriptor(
            [W.GPURenderPassColorAttachment(texture.createView(), [0.0, 0.0, 0.0, 1.0])], None))
        rpass.setPipeline(pipeline)
        rpass.draw(3)
        rpass.end()
        # WebGPU requires 256-byte row alignment.
        bytes_per_row = 256
        read = device.createBuffer(W.GPUBufferDescriptor(
            bytes_per_row * height, W.GPUBufferUsage.MAP_READ | W.GPUBufferUsage.COPY_DST))
        encoder.copyTextureToBuffer(
            W.GPUTexelCopyTextureInfo(texture),
            W.GPUTexelCopyBufferInfo(read, bytesPerRow=bytes_per_row), width=width, height=height)
        device.queue.submit([encoder.finish()])
        await read.mapAsync(W.GPUMapMode.READ)
        pixels = bytes(read.getMappedRange()._bytes)
        read.unmap()
        return pixels, bytes_per_row, width, height

    pixels, stride, width, height = asyncio.run(run())
    first = pixels[:4]
    last = pixels[(height - 1) * stride + (width - 1) * 4:][:4]
    assert first == bytes((255, 128, 0, 255))
    assert last == bytes((255, 128, 0, 255))


def test_sampler_binds_a_texture_for_a_second_pass():
    adapter = _adapter()

    async def run():
        device = await adapter.requestDevice()
        usage = W.GPUTextureUsage
        source = device.createTexture(W.GPUTextureDescriptor(
            [4, 4], "rgba8unorm", usage.RENDER_ATTACHMENT | usage.TEXTURE_BINDING))
        target = device.createTexture(W.GPUTextureDescriptor(
            [8, 8], "rgba8unorm", usage.RENDER_ATTACHMENT | usage.COPY_SRC))
        fill = device.createShaderModule(W.GPUShaderModuleDescriptor("""
            @vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
              let p = array<vec2<f32>, 3>(vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
              return vec4<f32>(p[i], 0.0, 1.0);
            }
            @fragment fn fs() -> @location(0) vec4<f32> { return vec4<f32>(0.0, 0.5, 1.0, 1.0); }"""))
        blit = device.createShaderModule(W.GPUShaderModuleDescriptor("""
            struct Out { @builtin(position) clip: vec4<f32>, @location(0) uv: vec2<f32> };
            @group(0) @binding(0) var tex: texture_2d<f32>;
            @group(0) @binding(1) var samp: sampler;
            @vertex fn vs(@builtin(vertex_index) i: u32) -> Out {
              let p = array<vec2<f32>, 3>(vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
              var o: Out;
              o.clip = vec4<f32>(p[i], 0.0, 1.0);
              o.uv = vec2<f32>(p[i].x * 0.5 + 0.5, 0.5 - p[i].y * 0.5);
              return o;
            }
            @fragment fn fs(o: Out) -> @location(0) vec4<f32> { return textureSample(tex, samp, o.uv); }"""))
        fill_pipe = device.createRenderPipeline(W.GPURenderPipelineDescriptor(
            W.GPUVertexState(fill, "vs", []),
            W.GPUFragmentState(fill, "fs", [W.GPUColorTargetState("rgba8unorm")]),
            W.GPUPrimitiveState(), None))
        layout = device.createBindGroupLayout(W.GPUBindGroupLayoutDescriptor([
            W.GPUBindGroupLayoutEntry(0, W.GPUShaderStage.FRAGMENT, texture=W.GPUTextureBindingLayout()),
            W.GPUBindGroupLayoutEntry(1, W.GPUShaderStage.FRAGMENT, sampler=W.GPUSamplerBindingLayout()),
        ]))
        blit_pipe = device.createRenderPipeline(W.GPURenderPipelineDescriptor(
            W.GPUVertexState(blit, "vs", []),
            W.GPUFragmentState(blit, "fs", [W.GPUColorTargetState("rgba8unorm")]),
            W.GPUPrimitiveState(), None,
            device.createPipelineLayout(W.GPUPipelineLayoutDescriptor([layout]))))
        sampler = device.createSampler(magFilter="linear", minFilter="linear", label="bilinear")
        assert isinstance(sampler, W.GPUSampler) and sampler.label == "bilinear"
        bind = device.createBindGroup(W.GPUBindGroupDescriptor(
            layout, [W.GPUBindGroupEntry(0, source.createView()), W.GPUBindGroupEntry(1, sampler)]))

        encoder = device.createCommandEncoder()
        rpass = encoder.beginRenderPass(W.GPURenderPassDescriptor(
            [W.GPURenderPassColorAttachment(source.createView(), [0.0, 0.0, 0.0, 1.0])], None))
        rpass.setPipeline(fill_pipe)
        rpass.draw(3)
        rpass.end()
        rpass = encoder.beginRenderPass(W.GPURenderPassDescriptor(
            [W.GPURenderPassColorAttachment(target.createView(), [0.0, 0.0, 0.0, 1.0])], None))
        rpass.setPipeline(blit_pipe)
        rpass.setBindGroup(0, bind)
        rpass.draw(3)
        rpass.end()
        read = device.createBuffer(W.GPUBufferDescriptor(
            256 * 8, W.GPUBufferUsage.MAP_READ | W.GPUBufferUsage.COPY_DST))
        encoder.copyTextureToBuffer(
            W.GPUTexelCopyTextureInfo(target),
            W.GPUTexelCopyBufferInfo(read, bytesPerRow=256), width=8, height=8)
        device.queue.submit([encoder.finish()])
        await read.mapAsync(W.GPUMapMode.READ)
        pixels = bytes(read.getMappedRange()._bytes)
        read.unmap()
        return pixels

    pixels = asyncio.run(run())
    assert pixels[:4] == bytes((0, 128, 255, 255))
    assert pixels[7 * 256 + 7 * 4:][:4] == bytes((0, 128, 255, 255))
