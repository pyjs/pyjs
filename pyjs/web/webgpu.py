from pyjs import js, js_object
from pyjs.web.events import EventTarget
from pyjs.web.html import HTMLCanvasElement


@js(builtin=True)
class Float32Array:
    def __init__(self, values: list[float] | int):
        self.byteLength = 0
        self.length = 0


@js(builtin=True)
class Uint16Array:
    def __init__(self, values: list[int] | int):
        self.byteLength = 0
        self.length = 0


@js(builtin=True)
class Uint32Array:
    def __init__(self, values: list[int] | int):
        self.byteLength = 0
        self.length = 0


@js(builtin=True)
class _GPUBufferUsage:
    def __init__(self):
        self.MAP_READ = 0x0001
        self.MAP_WRITE = 0x0002
        self.COPY_SRC = 0x0004
        self.COPY_DST = 0x0008
        self.INDEX = 0x0010
        self.VERTEX = 0x0020
        self.UNIFORM = 0x0040
        self.STORAGE = 0x0080
        self.INDIRECT = 0x0100
        self.QUERY_RESOLVE = 0x0200


GPUBufferUsage = _GPUBufferUsage()
js_object(GPUBufferUsage, builtin=True)


@js(builtin=True)
class _GPUTextureUsage:
    def __init__(self):
        self.COPY_SRC = 0x01
        self.COPY_DST = 0x02
        self.TEXTURE_BINDING = 0x04
        self.STORAGE_BINDING = 0x08
        self.RENDER_ATTACHMENT = 0x10


GPUTextureUsage = _GPUTextureUsage()
js_object(GPUTextureUsage, builtin=True)


@js(builtin=True)
class _GPUShaderStage:
    def __init__(self):
        self.VERTEX = 0x1
        self.FRAGMENT = 0x2
        self.COMPUTE = 0x4


GPUShaderStage = _GPUShaderStage()
js_object(GPUShaderStage, builtin=True)


@js(builtin=True)
class _GPUColorWrite:
    def __init__(self):
        self.RED = 0x1
        self.GREEN = 0x2
        self.BLUE = 0x4
        self.ALPHA = 0x8
        self.ALL = 0xF


GPUColorWrite = _GPUColorWrite()
js_object(GPUColorWrite, builtin=True)


@js(builtin=True)
class _GPUMapMode:
    def __init__(self):
        self.READ = 0x1
        self.WRITE = 0x2


GPUMapMode = _GPUMapMode()
js_object(GPUMapMode, builtin=True)


@js
class GPURequestAdapterOptions:
    def __init__(self, power_preference: str = "high-performance"):
        self.powerPreference = power_preference


@js
class GPUDeviceDescriptor:
    def __init__(self, label: str = ""):
        self.label = label


@js
class GPUCanvasConfiguration:
    def __init__(
        self,
        device: GPUDevice,
        format: str,
        usage: int = 0x10,
        alpha_mode: str = "opaque",
    ):
        self.device = device
        self.format = format
        self.usage = usage
        self.alphaMode = alpha_mode


@js
class GPUBufferDescriptor:
    def __init__(
        self,
        size: int,
        usage: int,
        label: str = "",
        mapped_at_creation: bool = False,
    ):
        self.size = size
        self.usage = usage
        self.label = label
        self.mappedAtCreation = mapped_at_creation


@js
class GPUShaderModuleDescriptor:
    def __init__(self, code: str, label: str = ""):
        self.code = code
        self.label = label


@js
class GPUExtent3D:
    def __init__(self, width: int, height: int, depth_or_array_layers: int = 1):
        self.width = width
        self.height = height
        self.depthOrArrayLayers = depth_or_array_layers


@js
class GPUTextureDescriptor:
    def __init__(
        self,
        size: GPUExtent3D,
        format: str,
        usage: int,
        label: str = "",
        dimension: str = "2d",
        mip_level_count: int = 1,
        sample_count: int = 1,
    ):
        self.size = size
        self.format = format
        self.usage = usage
        self.label = label
        self.dimension = dimension
        self.mipLevelCount = mip_level_count
        self.sampleCount = sample_count


@js
class GPUVertexAttribute:
    def __init__(self, format: str, offset: int, shader_location: int):
        self.format = format
        self.offset = offset
        self.shaderLocation = shader_location


@js
class GPUVertexBufferLayout:
    def __init__(
        self,
        array_stride: int,
        attributes: list[GPUVertexAttribute],
        step_mode: str = "vertex",
    ):
        self.arrayStride = array_stride
        self.attributes = attributes
        self.stepMode = step_mode


@js
class GPUVertexState:
    def __init__(
        self,
        module: GPUShaderModule,
        entry_point: str,
        buffers: list[GPUVertexBufferLayout],
    ):
        self.module = module
        self.entryPoint = entry_point
        self.buffers = buffers


@js
class GPUColorTargetState:
    def __init__(self, format: str, write_mask: int = 0xF):
        self.format = format
        self.writeMask = write_mask


@js
class GPUFragmentState:
    def __init__(
        self,
        module: GPUShaderModule,
        entry_point: str,
        targets: list[GPUColorTargetState],
    ):
        self.module = module
        self.entryPoint = entry_point
        self.targets = targets


@js
class GPUPrimitiveState:
    def __init__(
        self,
        topology: str = "triangle-list",
        cull_mode: str = "back",
        front_face: str = "ccw",
    ):
        self.topology = topology
        self.cullMode = cull_mode
        self.frontFace = front_face


@js
class GPUDepthStencilState:
    def __init__(
        self,
        format: str = "depth24plus",
        depth_write_enabled: bool = True,
        depth_compare: str = "less",
    ):
        self.format = format
        self.depthWriteEnabled = depth_write_enabled
        self.depthCompare = depth_compare


@js
class GPURenderPipelineDescriptor:
    def __init__(
        self,
        vertex: GPUVertexState,
        fragment: GPUFragmentState,
        primitive: GPUPrimitiveState,
        depth_stencil: GPUDepthStencilState,
        layout: str = "auto",
        label: str = "",
    ):
        self.vertex = vertex
        self.fragment = fragment
        self.primitive = primitive
        self.depthStencil = depth_stencil
        self.layout = layout
        self.label = label


@js
class GPUBufferBinding:
    def __init__(self, buffer: GPUBuffer, offset: int = 0):
        self.buffer = buffer
        self.offset = offset


@js
class GPUBindGroupEntry:
    def __init__(self, binding: int, resource: GPUBufferBinding):
        self.binding = binding
        self.resource = resource


@js
class GPUBindGroupDescriptor:
    def __init__(
        self,
        layout: GPUBindGroupLayout,
        entries: list[GPUBindGroupEntry],
        label: str = "",
    ):
        self.layout = layout
        self.entries = entries
        self.label = label


@js
class GPUColor:
    def __init__(self, red: float, green: float, blue: float, alpha: float = 1.0):
        self.r = red
        self.g = green
        self.b = blue
        self.a = alpha


@js
class GPURenderPassColorAttachment:
    def __init__(
        self,
        view: GPUTextureView,
        clear_value: GPUColor,
        load_op: str = "clear",
        store_op: str = "store",
    ):
        self.view = view
        self.clearValue = clear_value
        self.loadOp = load_op
        self.storeOp = store_op


@js
class GPURenderPassDepthStencilAttachment:
    def __init__(
        self,
        view: GPUTextureView,
        depth_clear_value: float = 1.0,
        depth_load_op: str = "clear",
        depth_store_op: str = "store",
    ):
        self.view = view
        self.depthClearValue = depth_clear_value
        self.depthLoadOp = depth_load_op
        self.depthStoreOp = depth_store_op


@js
class GPURenderPassDescriptor:
    def __init__(
        self,
        color_attachments: list[GPURenderPassColorAttachment],
        depth_stencil_attachment: GPURenderPassDepthStencilAttachment,
        label: str = "",
    ):
        self.colorAttachments = color_attachments
        self.depthStencilAttachment = depth_stencil_attachment
        self.label = label


@js(builtin=True)
class GPUBuffer:
    def __init__(self):
        self.size = 0

    def destroy(self): ...


@js(builtin=True)
class GPUTextureView:
    pass


@js(builtin=True)
class GPUTexture:
    def createView(self) -> GPUTextureView: ...

    def destroy(self): ...


@js(builtin=True)
class GPUShaderModule:
    pass


@js(builtin=True)
class GPUBindGroupLayout:
    pass


@js(builtin=True)
class GPUBindGroup:
    pass


@js(builtin=True)
class GPURenderPipeline:
    def getBindGroupLayout(self, index: int) -> GPUBindGroupLayout: ...


@js(builtin=True)
class GPUCommandBuffer:
    pass


@js(builtin=True)
class GPURenderPassEncoder:
    def setPipeline(self, pipeline: GPURenderPipeline): ...

    def setVertexBuffer(self, slot: int, buffer: GPUBuffer): ...

    def setIndexBuffer(self, buffer: GPUBuffer, index_format: str): ...

    def setBindGroup(self, index: int, bind_group: GPUBindGroup): ...

    def draw(
        self,
        vertex_count: int,
        instance_count: int = 1,
        first_vertex: int = 0,
        first_instance: int = 0,
    ): ...

    def drawIndexed(
        self,
        index_count: int,
        instance_count: int = 1,
        first_index: int = 0,
        base_vertex: int = 0,
        first_instance: int = 0,
    ): ...

    def end(self): ...


@js(builtin=True)
class GPUCommandEncoder:
    def beginRenderPass(
        self, descriptor: GPURenderPassDescriptor
    ) -> GPURenderPassEncoder: ...

    def finish(self) -> GPUCommandBuffer: ...


@js(builtin=True)
class GPUQueue:
    def writeBuffer(
        self,
        buffer: GPUBuffer,
        buffer_offset: int,
        data: Float32Array | Uint16Array | Uint32Array,
    ): ...

    def submit(self, command_buffers: list[GPUCommandBuffer]): ...

    async def onSubmittedWorkDone(self) -> None: ...


@js(builtin=True)
class GPUDevice(EventTarget):
    def __init__(self):
        super().__init__()
        self.queue = GPUQueue()

    def createBuffer(self, descriptor: GPUBufferDescriptor) -> GPUBuffer: ...

    def createTexture(self, descriptor: GPUTextureDescriptor) -> GPUTexture: ...

    def createShaderModule(
        self, descriptor: GPUShaderModuleDescriptor
    ) -> GPUShaderModule: ...

    def createRenderPipeline(
        self, descriptor: GPURenderPipelineDescriptor
    ) -> GPURenderPipeline: ...

    async def createRenderPipelineAsync(
        self, descriptor: GPURenderPipelineDescriptor
    ) -> GPURenderPipeline: ...

    def createBindGroup(self, descriptor: GPUBindGroupDescriptor) -> GPUBindGroup: ...

    def createCommandEncoder(self) -> GPUCommandEncoder: ...

    def destroy(self): ...


@js(builtin=True)
class GPUAdapter:
    async def requestDevice(
        self, descriptor: GPUDeviceDescriptor | None = None
    ) -> GPUDevice: ...


@js(builtin=True)
class GPU:
    async def requestAdapter(
        self, options: GPURequestAdapterOptions | None = None
    ) -> GPUAdapter | None: ...

    def getPreferredCanvasFormat(self) -> str: ...


@js(builtin=True)
class Navigator:
    def __init__(self):
        self.gpu = GPU()


navigator = Navigator()
js_object(navigator, builtin=True)


@js(builtin=True)
class GPUCanvasContext:
    def configure(self, configuration: GPUCanvasConfiguration): ...

    def getCurrentTexture(self) -> GPUTexture: ...

    def unconfigure(self): ...


@js(builtin=True, inline="{canvas}.getContext('webgpu')")
def get_webgpu_context(canvas: HTMLCanvasElement) -> GPUCanvasContext: ...


@js(builtin=True)
def requestAnimationFrame(callback: callable) -> int: ...


@js(builtin=True)
def cancelAnimationFrame(request_id: int): ...
