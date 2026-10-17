from pyjs import js
from pyjs.javascript import (
    ArrayBuffer,
    BigInt64Array,
    BigUint64Array,
    DataView,
    Float16Array,
    Float32Array,
    Float64Array,
    Int8Array,
    Int16Array,
    Int32Array,
    SharedArrayBuffer,
    Uint8Array,
    Uint8ClampedArray,
    Uint16Array,
    Uint32Array,
)
from pyjs.web._webgpu import buffer_source_bytes, lower, request_adapter, wrap
from pyjs.web.dom import DOMException
from pyjs.web.events import Event, EventTarget
from pyjs.web.html import (
    HTMLCanvasElement,
    HTMLImageElement,
    HTMLVideoElement,
    ImageBitmap,
    ImageData,
    OffscreenCanvas,
)


@js.native
class _GPUBufferUsage:
    def __init__(self):
        self.MAP_READ = 1
        self.MAP_WRITE = 2
        self.COPY_SRC = 4
        self.COPY_DST = 8
        self.INDEX = 16
        self.VERTEX = 32
        self.UNIFORM = 64
        self.STORAGE = 128
        self.INDIRECT = 256
        self.QUERY_RESOLVE = 512


GPUBufferUsage = _GPUBufferUsage()
js.native(GPUBufferUsage)


@js.native
class _GPUTextureUsage:
    def __init__(self):
        self.COPY_SRC = 1
        self.COPY_DST = 2
        self.TEXTURE_BINDING = 4
        self.STORAGE_BINDING = 8
        self.RENDER_ATTACHMENT = 16


GPUTextureUsage = _GPUTextureUsage()
js.native(GPUTextureUsage)


@js.native
class _GPUShaderStage:
    def __init__(self):
        self.VERTEX = 1
        self.FRAGMENT = 2
        self.COMPUTE = 4


GPUShaderStage = _GPUShaderStage()
js.native(GPUShaderStage)


@js.native
class _GPUColorWrite:
    def __init__(self):
        self.RED = 1
        self.GREEN = 2
        self.BLUE = 4
        self.ALPHA = 8
        self.ALL = 15


GPUColorWrite = _GPUColorWrite()
js.native(GPUColorWrite)


@js.native
class _GPUMapMode:
    def __init__(self):
        self.READ = 1
        self.WRITE = 2


GPUMapMode = _GPUMapMode()
js.native(GPUMapMode)


@js.dictionary
class GPURequestAdapterOptions:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        power_preference: str | None = "high-performance",
        *,
        featureLevel: str = "core",
        forceFallbackAdapter: bool = False,
        xrCompatible: bool = False,
    ):
        self.powerPreference = power_preference
        self.featureLevel = featureLevel
        self.forceFallbackAdapter = forceFallbackAdapter
        self.xrCompatible = xrCompatible


@js.dictionary
class GPUBufferBindingLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        hasDynamicOffset: bool = False,
        minBindingSize: int = 0,
        type: str = "uniform",
    ):
        self.hasDynamicOffset = hasDynamicOffset
        self.minBindingSize = minBindingSize
        self.type = type


@js.dictionary
class GPUCanvasConfiguration:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        device: GPUDevice,
        format: str,
        usage: int = 16,
        alpha_mode: str = "opaque",
        *,
        colorSpace: str = "srgb",
        toneMapping: GPUCanvasToneMapping | None = None,
        viewFormats: list[str] | None = None,
    ):
        self.device = device
        self.format = format
        self.usage = usage
        self.alphaMode = alpha_mode
        self.colorSpace = colorSpace
        if toneMapping is None:
            toneMapping = GPUCanvasToneMapping()
        self.toneMapping = toneMapping
        if viewFormats is None:
            viewFormats = []
        self.viewFormats = viewFormats


@js.dictionary
class GPUExtent3D:
    def __init__(self, width: int, height: int, depth_or_array_layers: int = 1):
        self.width = width
        self.height = height
        self.depthOrArrayLayers = depth_or_array_layers


@js.native
class GPUUncapturedErrorEvent(Event):
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUUncapturedErrorEvent

    Browser support: Chrome 144, Safari 26"""

    def __init__(
        self, type: str, gpuUncapturedErrorEventInitDict: GPUUncapturedErrorEventInit
    ):
        super().__init__()
        self.error = gpuUncapturedErrorEventInitDict.error


@js.dictionary
class GPUUncapturedErrorEventInit:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, error: GPUError):
        self.error = error


@js.dictionary
class GPUVertexAttribute:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, format: str, offset: int, shader_location: int):
        self.format = format
        self.offset = offset
        self.shaderLocation = shader_location


@js.dictionary
class GPUVertexBufferLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        array_stride: int,
        attributes: list[GPUVertexAttribute],
        step_mode: str = "vertex",
    ):
        self.arrayStride = array_stride
        self.attributes = attributes
        self.stepMode = step_mode


@js.dictionary
class GPUCanvasToneMapping:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, mode: str = "standard"):
        self.mode = mode


@js.dictionary
class GPUColorDict:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, a: float, b: float, g: float, r: float):
        self.a = a
        self.b = b
        self.g = g
        self.r = r


@js.dictionary
class GPUColorTargetState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self, format: str, write_mask: int = 15, *, blend: GPUBlendState | None = None
    ):
        self.format = format
        self.writeMask = write_mask
        if blend is not None:
            self.blend = blend


@js.native
class GPUDeviceLostInfo:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUDeviceLostInfo

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.message: str = ""
        self.reason: str = ""


@js.native
class GPUError:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUError

    Browser support: Chrome 144"""

    def __init__(self):
        self.message: str = ""


@js.dictionary
class GPUExtent3DDict:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, width: int, depthOrArrayLayers: int = 1, height: int = 1):
        self.width = width
        self.depthOrArrayLayers = depthOrArrayLayers
        self.height = height


@js.native
class GPUExternalTexture:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUExternalTexture

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""


@js.dictionary
class GPUExternalTextureBindingLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self): ...


@js.dictionary
class GPUMultisampleState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self, alphaToCoverageEnabled: bool = False, count: int = 1, mask: int = 4294967295
    ):
        self.alphaToCoverageEnabled = alphaToCoverageEnabled
        self.count = count
        self.mask = mask


@js.dictionary
class GPUObjectDescriptorBase:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, label: str = ""):
        self.label = label


@js.dictionary
class GPUOrigin2DDict:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, x: int = 0, y: int = 0):
        self.x = x
        self.y = y


@js.dictionary
class GPUOrigin3DDict:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, x: int = 0, y: int = 0, z: int = 0):
        self.x = x
        self.y = y
        self.z = z


@js.native
class GPUPipelineError(DOMException):
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUPipelineError

    Browser support: Chrome 144, Safari 26"""

    def __init__(self, message: str = "", *, options: GPUPipelineErrorInit):
        super().__init__()
        self.reason = options.reason


@js.dictionary
class GPUPipelineErrorInit:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, reason: str):
        self.reason = reason


@js.native
class GPUPipelineLayout:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUPipelineLayout

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""


@js.dictionary
class GPUPrimitiveState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        topology: str = "triangle-list",
        cull_mode: str = "back",
        front_face: str = "ccw",
        *,
        stripIndexFormat: str | None = None,
        unclippedDepth: bool = False,
    ):
        self.topology = topology
        self.cullMode = cull_mode
        self.frontFace = front_face
        if stripIndexFormat is not None:
            self.stripIndexFormat = stripIndexFormat
        self.unclippedDepth = unclippedDepth


@js.native
class GPUCompilationInfo:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUCompilationInfo

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.messages: list[GPUCompilationMessage] = []


@js.native
class GPUCompilationMessage:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUCompilationMessage

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.length: int = 0
        self.lineNum: int = 0
        self.linePos: int = 0
        self.message: str = ""
        self.offset: int = 0
        self.type: str = ""


@js.native
class GPUComputePassEncoder:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUComputePassEncoder

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""

    def dispatchWorkgroups(
        self, workgroupCountX: int, workgroupCountY: int = 1, workgroupCountZ: int = 1
    ) -> None:
        self._native.dispatch_workgroups(
            workgroupCountX, workgroupCountY, workgroupCountZ
        )

    def dispatchWorkgroupsIndirect(
        self, indirectBuffer: GPUBuffer, indirectOffset: int
    ) -> None: ...

    def end(self) -> None:
        self._native.end()

    def insertDebugMarker(self, markerLabel: str) -> None: ...

    def popDebugGroup(self) -> None: ...

    def pushDebugGroup(self, groupLabel: str) -> None: ...

    def setBindGroup(
        self,
        index: int,
        bindGroup: GPUBindGroup | None,
        dynamicOffsets: list[int] | None = None,
    ) -> None:
        self._native.set_bind_group(
            index,
            bindGroup._native if bindGroup is not None else None,
            dynamicOffsets or (),
        )

    def setImmediates(
        self,
        rangeOffset: int,
        data: ArrayBuffer
        | SharedArrayBuffer
        | Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView,
        dataOffset: int = 0,
        dataSize: int | None = None,
    ) -> None: ...

    def setPipeline(self, pipeline: GPUComputePipeline) -> None:
        self._native.set_pipeline(pipeline._native)


@js.dictionary
class GPUComputePassTimestampWrites:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        querySet: GPUQuerySet,
        beginningOfPassWriteIndex: int | None = None,
        endOfPassWriteIndex: int | None = None,
    ):
        self.querySet = querySet
        if beginningOfPassWriteIndex is not None:
            self.beginningOfPassWriteIndex = beginningOfPassWriteIndex
        if endOfPassWriteIndex is not None:
            self.endOfPassWriteIndex = endOfPassWriteIndex


@js.native
class GPUComputePipeline:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUComputePipeline

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""

    def getBindGroupLayout(self, index: int) -> GPUBindGroupLayout:
        native = self._native.get_bind_group_layout(index)
        return wrap(GPUBindGroupLayout, native, label=getattr(native, "label", ""))


@js.dictionary
class GPUCopyExternalImageSourceInfo:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        source: ImageBitmap
        | ImageData
        | HTMLImageElement
        | HTMLVideoElement
        | VideoFrame
        | HTMLCanvasElement
        | OffscreenCanvas,
        flipY: bool = False,
        origin: list[int] | GPUOrigin2DDict | None = None,
    ):
        self.source = source
        self.flipY = flipY
        if origin is None:
            origin = list[int]()
        self.origin = origin


@js.dictionary
class GPUDepthStencilState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        format: str = "depth24plus",
        depth_write_enabled: bool | None = True,
        depth_compare: str | None = "less",
        *,
        depthBias: int = 0,
        depthBiasClamp: float = 0,
        depthBiasSlopeScale: float = 0,
        stencilBack: GPUStencilFaceState | None = None,
        stencilFront: GPUStencilFaceState | None = None,
        stencilReadMask: int = 4294967295,
        stencilWriteMask: int = 4294967295,
    ):
        self.format = format
        self.depthWriteEnabled = depth_write_enabled
        self.depthCompare = depth_compare
        self.depthBias = depthBias
        self.depthBiasClamp = depthBiasClamp
        self.depthBiasSlopeScale = depthBiasSlopeScale
        if stencilBack is None:
            stencilBack = GPUStencilFaceState()
        self.stencilBack = stencilBack
        if stencilFront is None:
            stencilFront = GPUStencilFaceState()
        self.stencilFront = stencilFront
        self.stencilReadMask = stencilReadMask
        self.stencilWriteMask = stencilWriteMask


@js.dictionary
class GPUBufferBinding:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, buffer: GPUBuffer, offset: int = 0, *, size: int | None = None):
        self.buffer = buffer
        self.offset = offset
        if size is not None:
            self.size = size


@js.dictionary
class GPUBindGroupEntry:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        binding: int,
        resource: GPUSampler
        | GPUTexture
        | GPUTextureView
        | GPUBuffer
        | GPUBufferBinding
        | GPUExternalTexture,
    ):
        self.binding = binding
        self.resource = resource


@js.native
class VideoFrame:
    """WebIDL source: @webref/idl/webcodecs.idl

    MDN: https://developer.mozilla.org/docs/Web/API/VideoFrame

    Browser support: Chrome 94, Safari 16.4"""

    pass


@js.native
class WGSLLanguageFeatures:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WGSLLanguageFeatures

    Browser support: Chrome 144, Safari 26"""

    pass


@js.dictionary
class GPUColor:
    def __init__(self, red: float, green: float, blue: float, alpha: float = 1.0):
        self.r = red
        self.g = green
        self.b = blue
        self.a = alpha


@js.native
class GPURenderBundle:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPURenderBundle

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""


@js.native
class GPURenderBundleEncoder:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPURenderBundleEncoder

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""

    def draw(
        self,
        vertexCount: int,
        instanceCount: int = 1,
        firstVertex: int = 0,
        firstInstance: int = 0,
    ) -> None: ...

    def drawIndexed(
        self,
        indexCount: int,
        instanceCount: int = 1,
        firstIndex: int = 0,
        baseVertex: int = 0,
        firstInstance: int = 0,
    ) -> None: ...

    def drawIndexedIndirect(
        self, indirectBuffer: GPUBuffer, indirectOffset: int
    ) -> None: ...

    def drawIndirect(self, indirectBuffer: GPUBuffer, indirectOffset: int) -> None: ...

    def finish(self, *, label: str = "") -> GPURenderBundle: ...

    def insertDebugMarker(self, markerLabel: str) -> None: ...

    def popDebugGroup(self) -> None: ...

    def pushDebugGroup(self, groupLabel: str) -> None: ...

    def setBindGroup(
        self,
        index: int,
        bindGroup: GPUBindGroup | None,
        dynamicOffsets: list[int] | None = None,
    ) -> None: ...

    def setImmediates(
        self,
        rangeOffset: int,
        data: ArrayBuffer
        | SharedArrayBuffer
        | Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView,
        dataOffset: int = 0,
        dataSize: int | None = None,
    ) -> None: ...

    def setIndexBuffer(
        self,
        buffer: GPUBuffer,
        indexFormat: str,
        offset: int = 0,
        size: int | None = None,
    ) -> None: ...

    def setPipeline(self, pipeline: GPURenderPipeline) -> None: ...

    def setVertexBuffer(
        self,
        slot: int,
        buffer: GPUBuffer | None,
        offset: int = 0,
        size: int | None = None,
    ) -> None: ...


@js.dictionary
class GPURenderPassColorAttachment:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        view: GPUTexture | GPUTextureView,
        clear_value: list[float] | GPUColor | GPUColorDict | None,
        load_op: str = "clear",
        store_op: str = "store",
        *,
        depthSlice: int | None = None,
        resolveTarget: GPUTexture | GPUTextureView | None = None,
    ):
        self.view = view
        self.clearValue = clear_value
        self.loadOp = load_op
        self.storeOp = store_op
        if depthSlice is not None:
            self.depthSlice = depthSlice
        if resolveTarget is not None:
            self.resolveTarget = resolveTarget


@js.dictionary
class GPURenderPassDepthStencilAttachment:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        view: GPUTexture | GPUTextureView,
        depth_clear_value: float | None = 1.0,
        depth_load_op: str | None = "clear",
        depth_store_op: str | None = "store",
        *,
        depthReadOnly: bool = False,
        stencilClearValue: int = 0,
        stencilLoadOp: str | None = None,
        stencilReadOnly: bool = False,
        stencilStoreOp: str | None = None,
    ):
        self.view = view
        self.depthClearValue = depth_clear_value
        self.depthLoadOp = depth_load_op
        self.depthStoreOp = depth_store_op
        self.depthReadOnly = depthReadOnly
        self.stencilClearValue = stencilClearValue
        if stencilLoadOp is not None:
            self.stencilLoadOp = stencilLoadOp
        self.stencilReadOnly = stencilReadOnly
        if stencilStoreOp is not None:
            self.stencilStoreOp = stencilStoreOp


@js.dictionary
class GPUBindGroupLayoutEntry:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        binding: int,
        visibility: int,
        buffer: GPUBufferBindingLayout | None = None,
        externalTexture: GPUExternalTextureBindingLayout | None = None,
        sampler: GPUSamplerBindingLayout | None = None,
        storageTexture: GPUStorageTextureBindingLayout | None = None,
        texture: GPUTextureBindingLayout | None = None,
    ):
        self.binding = binding
        self.visibility = visibility
        if buffer is not None:
            self.buffer = buffer
        if externalTexture is not None:
            self.externalTexture = externalTexture
        if sampler is not None:
            self.sampler = sampler
        if storageTexture is not None:
            self.storageTexture = storageTexture
        if texture is not None:
            self.texture = texture


@js.dictionary
class GPUBlendComponent:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self, dstFactor: str = "zero", operation: str = "add", srcFactor: str = "one"
    ):
        self.dstFactor = dstFactor
        self.operation = operation
        self.srcFactor = srcFactor


@js.dictionary
class GPUBlendState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, alpha: GPUBlendComponent, color: GPUBlendComponent):
        self.alpha = alpha
        self.color = color


@js.native
class GPUBuffer:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUBuffer

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""
        self.mapState: str = ""
        self.size: int = 0
        self.usage: int = 0
        self._map_mode: int = 0
        self._map_offset: int = 0
        self._pending: object = None

    def destroy(self) -> None:
        self._native.destroy()
        self._pending = None
        self.mapState = "unmapped"

    def getMappedRange(self, offset: int = 0, size: int | None = None) -> ArrayBuffer:
        if self._pending is None:
            raise RuntimeError("buffer is not mapped")
        if offset % 8:
            raise ValueError("mapped range offset must be a multiple of 8")
        start = offset - self._map_offset
        stop = len(self._pending) if size is None else start + size
        if start < 0 or stop < start or stop > len(self._pending):
            raise ValueError("requested range is outside the mapped buffer range")
        if (stop - start) % 4:
            raise ValueError("mapped range size must be a multiple of 4")
        view = ArrayBuffer(stop - start)
        view._bytes = memoryview(self._pending)[start:stop]
        return view

    async def mapAsync(self, mode: int, offset: int = 0, size: int | None = None) -> None:
        length = self.size - offset if size is None else size
        await self._native.map_async(mode, offset, length)
        if mode & GPUMapMode.READ:
            self._pending = bytearray(self._native.read_mapped(offset, length))
        else:
            self._pending = bytearray(length)
        self._map_mode = mode
        self._map_offset = offset
        self.mapState = "mapped"

    def unmap(self) -> None:
        pending = self._pending
        if pending is not None and self._map_mode & GPUMapMode.WRITE:
            self._native.write_mapped(pending, self._map_offset)
        if pending is not None:
            self._native.unmap()
        self._pending = None
        self._map_mode = 0
        self._map_offset = 0
        self.mapState = "unmapped"


@js.dictionary
class GPUTextureBindingLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        multisampled: bool = False,
        sampleType: str = "float",
        viewDimension: str = "2d",
    ):
        self.multisampled = multisampled
        self.sampleType = sampleType
        self.viewDimension = viewDimension


@js.native
class GPUTextureView:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUTextureView

    Browser support: Chrome 144, Safari 26"""

    pass

    def __init__(self):
        self.label: str = ""


@js.dictionary
class GPUShaderModuleCompilationHint:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, entryPoint: str, layout: GPUPipelineLayout | str | None = None):
        self.entryPoint = entryPoint
        if layout is not None:
            self.layout = layout


@js.dictionary
class GPUStencilFaceState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        compare: str = "always",
        depthFailOp: str = "keep",
        failOp: str = "keep",
        passOp: str = "keep",
    ):
        self.compare = compare
        self.depthFailOp = depthFailOp
        self.failOp = failOp
        self.passOp = passOp


@js.dictionary
class GPUStorageTextureBindingLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self, format: str, access: str = "write-only", viewDimension: str = "2d"
    ):
        self.format = format
        self.access = access
        self.viewDimension = viewDimension


@js.native
class GPUSupportedFeatures:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUSupportedFeatures

    Browser support: Chrome 144, Safari 26"""

    pass


@js.native
class GPUSupportedLimits:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUSupportedLimits

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.maxBindGroups: int = 0
        self.maxBindGroupsPlusVertexBuffers: int = 0
        self.maxBindingsPerBindGroup: int = 0
        self.maxBufferSize: int = 0
        self.maxColorAttachmentBytesPerSample: int = 0
        self.maxColorAttachments: int = 0
        self.maxComputeInvocationsPerWorkgroup: int = 0
        self.maxComputeWorkgroupSizeX: int = 0
        self.maxComputeWorkgroupSizeY: int = 0
        self.maxComputeWorkgroupSizeZ: int = 0
        self.maxComputeWorkgroupsPerDimension: int = 0
        self.maxComputeWorkgroupStorageSize: int = 0
        self.maxDynamicStorageBuffersPerPipelineLayout: int = 0
        self.maxDynamicUniformBuffersPerPipelineLayout: int = 0
        self.maxImmediateSize: int = 0
        self.maxInterStageShaderVariables: int = 0
        self.maxSampledTexturesPerShaderStage: int = 0
        self.maxSamplersPerShaderStage: int = 0
        self.maxStorageBufferBindingSize: int = 0
        self.maxStorageBuffersInFragmentStage: int = 0
        self.maxStorageBuffersInVertexStage: int = 0
        self.maxStorageBuffersPerShaderStage: int = 0
        self.maxStorageTexturesInFragmentStage: int = 0
        self.maxStorageTexturesInVertexStage: int = 0
        self.maxStorageTexturesPerShaderStage: int = 0
        self.maxTextureArrayLayers: int = 0
        self.maxTextureDimension1D: int = 0
        self.maxTextureDimension2D: int = 0
        self.maxTextureDimension3D: int = 0
        self.maxUniformBufferBindingSize: int = 0
        self.maxUniformBuffersPerShaderStage: int = 0
        self.maxVertexAttributes: int = 0
        self.maxVertexBufferArrayStride: int = 0
        self.maxVertexBuffers: int = 0
        self.minStorageBufferOffsetAlignment: int = 0
        self.minUniformBufferOffsetAlignment: int = 0


@js.dictionary
class GPUTexelCopyBufferLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        bytesPerRow: int | None = None,
        offset: int = 0,
        rowsPerImage: int | None = None,
    ):
        if bytesPerRow is not None:
            self.bytesPerRow = bytesPerRow
        self.offset = offset
        if rowsPerImage is not None:
            self.rowsPerImage = rowsPerImage


@js.dictionary
class GPUTexelCopyTextureInfo:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        texture: GPUTexture,
        aspect: str = "all",
        mipLevel: int = 0,
        origin: list[int] | GPUOrigin3DDict | None = None,
    ):
        self.texture = texture
        self.aspect = aspect
        self.mipLevel = mipLevel
        if origin is None:
            origin = list[int]()
        self.origin = origin


@js.native
class GPUTexture:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUTexture

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.depthOrArrayLayers: int = 0
        self.dimension: str = ""
        self.format: str = ""
        self.height: int = 0
        self.label: str = ""
        self.mipLevelCount: int = 0
        self.sampleCount: int = 0
        self.textureBindingViewDimension: str | None = None
        self.usage: int = 0
        self.width: int = 0

    def createView(
        self,
        *,
        label: str = "",
        format: str | None = None,
        dimension: str | None = None,
        usage: int = 0,
        aspect: str = "all",
        baseMipLevel: int = 0,
        mipLevelCount: int | None = None,
        baseArrayLayer: int = 0,
        arrayLayerCount: int | None = None,
        swizzle: str = "rgba",
    ) -> GPUTextureView:
        args = {
            "label": label,
            "usage": usage,
            "aspect": aspect,
            "base_mip_level": baseMipLevel,
            "mip_level_count": mipLevelCount,
            "base_array_layer": baseArrayLayer,
            "array_layer_count": arrayLayerCount,
            "swizzle": swizzle,
        }
        if format is not None:
            args["format"] = format
        if dimension is not None:
            args["dimension"] = dimension
        return wrap(GPUTextureView, self._native.create_view(**args), label=label)

    def destroy(self) -> None:
        self._native.destroy()


@js.native
class GPUSampler:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUSampler

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""


@js.dictionary
class GPUSamplerBindingLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, type: str = "filtering"):
        self.type = type


@js.native
class GPUShaderModule:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUShaderModule

    Browser support: Chrome 144, Safari 26"""

    pass

    def __init__(self):
        self.label: str = ""

    async def getCompilationInfo(self) -> GPUCompilationInfo: ...


@js.native
class GPUBindGroupLayout:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUBindGroupLayout

    Browser support: Chrome 144, Safari 26"""

    pass

    def __init__(self):
        self.label: str = ""


@js.native
class GPUAdapterInfo:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUAdapterInfo

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.architecture: str = ""
        self.description: str = ""
        self.device: str = ""
        self.isFallbackAdapter: bool = False
        self.subgroupMaxSize: int = 0
        self.subgroupMinSize: int = 0
        self.vendor: str = ""


@js.native
class GPUBindGroup:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUBindGroup

    Browser support: Chrome 144, Safari 26"""

    pass

    def __init__(self):
        self.label: str = ""


@js.dictionary
class GPURenderPassTimestampWrites:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        querySet: GPUQuerySet,
        beginningOfPassWriteIndex: int | None = None,
        endOfPassWriteIndex: int | None = None,
    ):
        self.querySet = querySet
        if beginningOfPassWriteIndex is not None:
            self.beginningOfPassWriteIndex = beginningOfPassWriteIndex
        if endOfPassWriteIndex is not None:
            self.endOfPassWriteIndex = endOfPassWriteIndex


@js.native
class GPURenderPipeline:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPURenderPipeline

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""

    def getBindGroupLayout(self, index: int) -> GPUBindGroupLayout:
        native = self._native.get_bind_group_layout(index)
        return wrap(GPUBindGroupLayout, native, label=getattr(native, "label", ""))


@js.native
class GPUCommandBuffer:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUCommandBuffer

    Browser support: Chrome 144, Safari 26"""

    pass

    def __init__(self):
        self.label: str = ""


@js.native
class GPURenderPassEncoder:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPURenderPassEncoder

    Browser support: Chrome 144, Safari 26"""

    def setPipeline(self, pipeline: GPURenderPipeline) -> None:
        self._native.set_pipeline(pipeline._native)

    def setScissorRect(self, x: int, y: int, width: int, height: int) -> None: ...

    def setStencilReference(self, reference: int) -> None: ...

    def setVertexBuffer(
        self,
        slot: int,
        buffer: GPUBuffer | None,
        offset: int = 0,
        size: int | None = None,
    ) -> None:
        self._native.set_vertex_buffer(
            slot, buffer._native if buffer is not None else None, offset, size
        )

    def setBlendConstant(self, *, r: float, g: float, b: float, a: float) -> None: ...

    def setImmediates(
        self,
        rangeOffset: int,
        data: ArrayBuffer
        | SharedArrayBuffer
        | Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView,
        dataOffset: int = 0,
        dataSize: int | None = None,
    ) -> None: ...

    def setIndexBuffer(
        self,
        buffer: GPUBuffer,
        indexFormat: str,
        offset: int = 0,
        size: int | None = None,
    ) -> None:
        self._native.set_index_buffer(buffer._native, indexFormat, offset, size)

    def endOcclusionQuery(self) -> None: ...

    def executeBundles(self, bundles: list[GPURenderBundle]) -> None: ...

    def insertDebugMarker(self, markerLabel: str) -> None: ...

    def popDebugGroup(self) -> None: ...

    def pushDebugGroup(self, groupLabel: str) -> None: ...

    def setBindGroup(
        self,
        index: int,
        bindGroup: GPUBindGroup | None,
        dynamicOffsets: list[int] | None = None,
    ) -> None:
        self._native.set_bind_group(
            index,
            bindGroup._native if bindGroup is not None else None,
            dynamicOffsets or (),
        )

    def __init__(self):
        self.label: str = ""

    def beginOcclusionQuery(self, queryIndex: int) -> None: ...

    def draw(
        self,
        vertexCount: int,
        instanceCount: int = 1,
        firstVertex: int = 0,
        firstInstance: int = 0,
    ) -> None:
        self._native.draw(vertexCount, instanceCount, firstVertex, firstInstance)

    def drawIndexed(
        self,
        indexCount: int,
        instanceCount: int = 1,
        firstIndex: int = 0,
        baseVertex: int = 0,
        firstInstance: int = 0,
    ) -> None:
        self._native.draw_indexed(
            indexCount, instanceCount, firstIndex, baseVertex, firstInstance
        )

    def drawIndexedIndirect(
        self, indirectBuffer: GPUBuffer, indirectOffset: int
    ) -> None: ...

    def drawIndirect(self, indirectBuffer: GPUBuffer, indirectOffset: int) -> None: ...

    def end(self) -> None:
        self._native.end()

    def setViewport(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        minDepth: float,
        maxDepth: float,
    ) -> None: ...


@js.native
class GPUCommandEncoder:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUCommandEncoder

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.label: str = ""

    def beginComputePass(
        self,
        *,
        label: str = "",
        timestampWrites: GPUComputePassTimestampWrites | None = None,
    ) -> GPUComputePassEncoder:
        timestamp_writes = None if timestampWrites is None else lower(timestampWrites)
        return wrap(
            GPUComputePassEncoder,
            self._native.begin_compute_pass(
                label=label, timestamp_writes=timestamp_writes
            ),
            label=label,
        )

    def beginRenderPass(
        self, descriptor: GPURenderPassDescriptor
    ) -> GPURenderPassEncoder:
        args = lower(descriptor)
        for attachment in args.get("color_attachments", []):
            if attachment and isinstance(attachment.get("clear_value"), dict):
                c = attachment["clear_value"]
                attachment["clear_value"] = (
                    c.get("r", 0.0),
                    c.get("g", 0.0),
                    c.get("b", 0.0),
                    c.get("a", 1.0),
                )
        return wrap(
            GPURenderPassEncoder,
            self._native.begin_render_pass(**args),
            label=descriptor.label,
        )

    def clearBuffer(
        self, buffer: GPUBuffer, offset: int = 0, size: int | None = None
    ) -> None: ...

    def copyBufferToBuffer(
        self, source: GPUBuffer, destination: GPUBuffer, size: int | None = None
    ) -> None:
        self._native.copy_buffer_to_buffer(
            source._native,
            0,
            destination._native,
            0,
            size if size is not None else min(source.size, destination.size),
        )

    def copyBufferToTexture(
        self,
        source: GPUTexelCopyBufferInfo,
        destination: GPUTexelCopyTextureInfo,
        *,
        width: int,
        height: int = 1,
        depthOrArrayLayers: int = 1,
    ) -> None: ...

    def copyTextureToBuffer(
        self,
        source: GPUTexelCopyTextureInfo,
        destination: GPUTexelCopyBufferInfo,
        *,
        width: int,
        height: int = 1,
        depthOrArrayLayers: int = 1,
    ) -> None:
        self._native.copy_texture_to_buffer(
            lower(source), lower(destination), (width, height, depthOrArrayLayers)
        )

    def copyTextureToTexture(
        self,
        source: GPUTexelCopyTextureInfo,
        destination: GPUTexelCopyTextureInfo,
        *,
        width: int,
        height: int = 1,
        depthOrArrayLayers: int = 1,
    ) -> None: ...

    def finish(self, *, label: str = "") -> GPUCommandBuffer:
        return wrap(GPUCommandBuffer, self._native.finish(label=label), label=label)

    def insertDebugMarker(self, markerLabel: str) -> None: ...

    def popDebugGroup(self) -> None: ...

    def pushDebugGroup(self, groupLabel: str) -> None: ...

    def resolveQuerySet(
        self,
        querySet: GPUQuerySet,
        firstQuery: int,
        queryCount: int,
        destination: GPUBuffer,
        destinationOffset: int,
    ) -> None: ...


@js.dictionary
class GPUProgrammableStage:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        module: GPUShaderModule,
        constants: dict[str, float] | None = None,
        entryPoint: str | None = None,
    ):
        self.module = module
        if constants is None:
            constants = {}
        self.constants = constants
        if entryPoint is not None:
            self.entryPoint = entryPoint


@js.native
class GPUQuerySet:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUQuerySet

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.count: int = 0
        self.label: str = ""
        self.type: str = ""

    def destroy(self) -> None: ...


@js.native
class GPUQueue:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUQueue

    Browser support: Chrome 144, Safari 26"""

    def writeBuffer(
        self,
        buffer: GPUBuffer,
        bufferOffset: int,
        data: ArrayBuffer
        | SharedArrayBuffer
        | Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView,
        dataOffset: int = 0,
        size: int | None = None,
    ) -> None:
        raw = buffer_source_bytes(data, dataOffset, size)
        self._native.write_buffer(buffer._native, bufferOffset, raw)

    def submit(self, commandBuffers: list[GPUCommandBuffer]) -> None:
        self._native.submit([command._native for command in commandBuffers])

    def __init__(self):
        self.label: str = ""

    def copyExternalImageToTexture(
        self,
        source: GPUCopyExternalImageSourceInfo,
        destination: GPUCopyExternalImageDestInfo,
        *,
        width: int,
        height: int = 1,
        depthOrArrayLayers: int = 1,
    ) -> None: ...

    async def onSubmittedWorkDone(self) -> None:
        await self._native.on_submitted_work_done_async()

    def writeTexture(
        self,
        destination: GPUTexelCopyTextureInfo,
        data: ArrayBuffer
        | SharedArrayBuffer
        | Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView,
        dataLayout: GPUTexelCopyBufferLayout,
        *,
        width: int,
        height: int = 1,
        depthOrArrayLayers: int = 1,
    ) -> None: ...


@js.native
class GPUDevice(EventTarget):
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUDevice

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        super().__init__()
        self.adapterInfo: GPUAdapterInfo = None
        self.features: GPUSupportedFeatures = None
        self.label: str = ""
        self.limits: GPUSupportedLimits = None
        self.lost: GPUDeviceLostInfo = None
        self.onuncapturederror: callable = None
        self.queue: GPUQueue = GPUQueue()

    def createBindGroupLayout(
        self, descriptor: GPUBindGroupLayoutDescriptor
    ) -> GPUBindGroupLayout:
        return wrap(
            GPUBindGroupLayout,
            self._native.create_bind_group_layout(**lower(descriptor)),
            label=descriptor.label,
        )

    def createBuffer(self, descriptor: GPUBufferDescriptor) -> GPUBuffer:
        args = lower(descriptor)
        mapped = args.get("mapped_at_creation", False)
        native = self._native.create_buffer(**args)
        buffer = wrap(
            GPUBuffer,
            native,
            size=native.size,
            usage=native.usage,
            label=args.get("label", ""),
        )
        buffer.mapState = "mapped" if mapped else "unmapped"
        buffer._pending = bytearray(native.size) if mapped else None
        buffer._map_mode = GPUMapMode.WRITE if mapped else 0
        buffer._map_offset = 0
        return buffer

    def createTexture(self, descriptor: GPUTextureDescriptor) -> GPUTexture:
        args = lower(descriptor)
        size = args["size"]
        if isinstance(size, dict):
            size = (
                size.get("width", 1),
                size.get("height", 1),
                size.get("depth_or_array_layers", 1),
            )
        args["size"] = tuple(size) + (1,) * (3 - len(size))
        native = self._native.create_texture(**args)
        return wrap(
            GPUTexture,
            native,
            width=args["size"][0],
            height=args["size"][1],
            depthOrArrayLayers=args["size"][2],
            format=args["format"],
            usage=args["usage"],
            dimension=args.get("dimension", "2d"),
            mipLevelCount=args.get("mip_level_count", 1),
            sampleCount=args.get("sample_count", 1),
            label=args.get("label", ""),
        )

    def createSampler(
        self,
        *,
        label: str = "",
        addressModeU: str = "clamp-to-edge",
        addressModeV: str = "clamp-to-edge",
        addressModeW: str = "clamp-to-edge",
        magFilter: str = "nearest",
        minFilter: str = "nearest",
        mipmapFilter: str = "nearest",
        lodMinClamp: float = 0,
        lodMaxClamp: float = 32,
        compare: str | None = None,
        maxAnisotropy: int = 1,
    ) -> GPUSampler:
        return wrap(
            GPUSampler,
            self._native.create_sampler(
                label=label,
                address_mode_u=addressModeU,
                address_mode_v=addressModeV,
                address_mode_w=addressModeW,
                mag_filter=magFilter,
                min_filter=minFilter,
                mipmap_filter=mipmapFilter,
                lod_min_clamp=lodMinClamp,
                lod_max_clamp=lodMaxClamp,
                compare=compare,
                max_anisotropy=maxAnisotropy,
            ),
            label=label,
        )

    def createShaderModule(
        self, descriptor: GPUShaderModuleDescriptor
    ) -> GPUShaderModule:
        return wrap(
            GPUShaderModule,
            self._native.create_shader_module(**lower(descriptor)),
            label=descriptor.label,
        )

    def createComputePipeline(
        self, descriptor: GPUComputePipelineDescriptor
    ) -> GPUComputePipeline:
        layout = descriptor.layout
        return wrap(
            GPUComputePipeline,
            self._native.create_compute_pipeline(
                label=descriptor.label,
                layout=layout if isinstance(layout, str) else layout._native,
                compute=lower(descriptor.compute),
            ),
            label=descriptor.label,
        )

    async def createComputePipelineAsync(
        self, descriptor: GPUComputePipelineDescriptor
    ) -> GPUComputePipeline:
        return self.createComputePipeline(descriptor)

    def createPipelineLayout(
        self, descriptor: GPUPipelineLayoutDescriptor
    ) -> GPUPipelineLayout:
        """Create a native layout while preserving nullable group slots.

        wgpu-py represents each WebGPU null slot with an empty native layout.
        """
        bind_group_layouts = []
        for layout in descriptor.bindGroupLayouts:
            native = (
                self._native.create_bind_group_layout(entries=[])
                if layout is None
                else layout._native
            )
            bind_group_layouts.append(native)
        return wrap(
            GPUPipelineLayout,
            self._native.create_pipeline_layout(
                label=descriptor.label,
                bind_group_layouts=bind_group_layouts,
                immediate_size=descriptor.immediateSize,
            ),
            label=descriptor.label,
        )

    def createQuerySet(self, descriptor: GPUQuerySetDescriptor) -> GPUQuerySet: ...

    def createRenderBundleEncoder(
        self, descriptor: GPURenderBundleEncoderDescriptor
    ) -> GPURenderBundleEncoder: ...

    def createRenderPipeline(
        self, descriptor: GPURenderPipelineDescriptor
    ) -> GPURenderPipeline:
        args = lower(descriptor)
        layout = descriptor.layout
        args["layout"] = layout if isinstance(layout, str) else layout._native
        return wrap(
            GPURenderPipeline,
            self._native.create_render_pipeline(**args),
            label=descriptor.label,
        )

    async def createRenderPipelineAsync(
        self, descriptor: GPURenderPipelineDescriptor
    ) -> GPURenderPipeline:
        return self.createRenderPipeline(descriptor)

    def createBindGroup(self, descriptor: GPUBindGroupDescriptor) -> GPUBindGroup:
        entries = []
        for entry in descriptor.entries:
            resource = entry.resource
            if isinstance(resource, GPUBufferBinding):
                size = getattr(resource, "size", None)
                lowered = {
                    "buffer": resource.buffer._native,
                    "offset": resource.offset,
                    "size": resource.buffer.size - resource.offset
                    if size is None
                    else size,
                }
            elif isinstance(resource, GPUBuffer):
                lowered = {"buffer": resource._native, "offset": 0, "size": resource.size}
            else:
                lowered = resource._native
            entries.append({"binding": entry.binding, "resource": lowered})
        return wrap(
            GPUBindGroup,
            self._native.create_bind_group(
                label=descriptor.label, layout=descriptor.layout._native, entries=entries
            ),
            label=descriptor.label,
        )

    def createCommandEncoder(self, *, label: str = "") -> GPUCommandEncoder:
        return wrap(
            GPUCommandEncoder,
            self._native.create_command_encoder(label=label),
            label=label,
        )

    def destroy(self) -> None: ...

    def importExternalTexture(
        self, descriptor: GPUExternalTextureDescriptor
    ) -> GPUExternalTexture: ...

    async def popErrorScope(self) -> GPUError | None: ...

    def pushErrorScope(self, filter: str) -> None: ...


@js.native
class GPUAdapter:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUAdapter

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.features: GPUSupportedFeatures = None
        self.info: GPUAdapterInfo = None
        self.limits: GPUSupportedLimits = None

    async def requestDevice(
        self,
        *,
        label: str = "",
        requiredFeatures: list[str] | None = None,
        requiredLimits: dict[str, int | None] | None = None,
        defaultQueue: GPUQueueDescriptor | None = None,
    ) -> GPUDevice:
        native = self._native.request_device_sync(
            label=label,
            required_features=requiredFeatures or (),
            required_limits=requiredLimits,
            default_queue=None if defaultQueue is None else lower(defaultQueue),
        )
        device = wrap(GPUDevice, native, label=label)
        queue_label = "" if defaultQueue is None else defaultQueue.label
        device.queue = wrap(GPUQueue, native.queue, label=queue_label)
        device.adapterInfo = self.info
        device.features = native.features
        device.limits = native.limits
        return device


@js.native
class GPU:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPU

    Browser support: Chrome 144, Safari 26"""

    async def requestAdapter(
        self,
        *,
        featureLevel: str = "core",
        powerPreference: str | None = None,
        forceFallbackAdapter: bool = False,
        xrCompatible: bool = False,
    ) -> GPUAdapter | None:
        """Request a native GPU adapter; XR compatibility is browser-only."""
        native = request_adapter(featureLevel, powerPreference, forceFallbackAdapter)
        if native is None:
            return None
        adapter = wrap(GPUAdapter, native)
        info = GPUAdapterInfo()
        raw = native.info
        info.vendor = raw.get("vendor", "")
        info.architecture = raw.get("architecture", "")
        info.device = raw.get("device", "")
        info.description = raw.get("description", "")
        info.isFallbackAdapter = bool(raw.get("adapter_type") == "CPU")
        adapter.info = info
        adapter.features = native.features
        adapter.limits = native.limits
        return adapter

    def __init__(self):
        self.wgslLanguageFeatures: WGSLLanguageFeatures = None

    def getPreferredCanvasFormat(self) -> str:
        """Return a format supported across wgpu-py's desktop backends."""
        return "bgra8unorm-srgb"


@js.native
class Navigator:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigator

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.gpu: GPU = GPU()


navigator = Navigator()
js.native(navigator)


@js.native
class GPUCanvasContext:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUCanvasContext

    Browser support: Chrome 144, Safari 26"""

    def __init__(self):
        self.canvas: HTMLCanvasElement | OffscreenCanvas = None

    def configure(self, configuration: GPUCanvasConfiguration) -> None: ...

    def getConfiguration(self) -> GPUCanvasConfiguration | None: ...

    def getCurrentTexture(self) -> GPUTexture: ...

    def unconfigure(self) -> None: ...


@js.dictionary
class GPUDeviceDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        label: str = "",
        *,
        defaultQueue: GPUQueueDescriptor | None = None,
        requiredFeatures: list[str] | None = None,
        requiredLimits: dict[str, int | None] | None = None,
    ):
        self.label = label
        if defaultQueue is None:
            defaultQueue = GPUQueueDescriptor()
        self.defaultQueue = defaultQueue
        if requiredFeatures is None:
            requiredFeatures = []
        self.requiredFeatures = requiredFeatures
        if requiredLimits is None:
            requiredLimits = {}
        self.requiredLimits = requiredLimits


@js.dictionary
class GPUBufferDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self, size: int, usage: int, label: str = "", mapped_at_creation: bool = False
    ):
        self.size = size
        self.usage = usage
        self.label = label
        self.mappedAtCreation = mapped_at_creation


@js.dictionary
class GPUShaderModuleDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        code: str,
        label: str = "",
        *,
        compilationHints: list[GPUShaderModuleCompilationHint] | None = None,
    ):
        self.code = code
        self.label = label
        if compilationHints is None:
            compilationHints = []
        self.compilationHints = compilationHints


@js.dictionary
class GPUTextureDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        size: list[int] | GPUExtent3D | GPUExtent3DDict,
        format: str,
        usage: int,
        label: str = "",
        dimension: str = "2d",
        mip_level_count: int = 1,
        sample_count: int = 1,
        *,
        textureBindingViewDimension: str | None = None,
        viewFormats: list[str] | None = None,
    ):
        self.size = size
        self.format = format
        self.usage = usage
        self.label = label
        self.dimension = dimension
        self.mipLevelCount = mip_level_count
        self.sampleCount = sample_count
        if textureBindingViewDimension is not None:
            self.textureBindingViewDimension = textureBindingViewDimension
        if viewFormats is None:
            viewFormats = []
        self.viewFormats = viewFormats


@js.dictionary
class GPUVertexState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        module: GPUShaderModule,
        entry_point: str | None,
        buffers: list[GPUVertexBufferLayout | None] | None,
        *,
        constants: dict[str, float] | None = None,
    ):
        self.module = module
        self.entryPoint = entry_point
        self.buffers = buffers
        if constants is None:
            constants = {}
        self.constants = constants


@js.dictionary
class GPUFragmentState:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        module: GPUShaderModule,
        entry_point: str | None,
        targets: list[GPUColorTargetState | None],
        *,
        constants: dict[str, float] | None = None,
    ):
        self.module = module
        self.entryPoint = entry_point
        self.targets = targets
        if constants is None:
            constants = {}
        self.constants = constants


@js.dictionary
class GPUTextureViewDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        arrayLayerCount: int | None = None,
        aspect: str = "all",
        baseArrayLayer: int = 0,
        baseMipLevel: int = 0,
        dimension: str | None = None,
        format: str | None = None,
        label: str = "",
        mipLevelCount: int | None = None,
        swizzle: str = "rgba",
        usage: int = 0,
    ):
        if arrayLayerCount is not None:
            self.arrayLayerCount = arrayLayerCount
        self.aspect = aspect
        self.baseArrayLayer = baseArrayLayer
        self.baseMipLevel = baseMipLevel
        if dimension is not None:
            self.dimension = dimension
        if format is not None:
            self.format = format
        self.label = label
        if mipLevelCount is not None:
            self.mipLevelCount = mipLevelCount
        self.swizzle = swizzle
        self.usage = usage


@js.dictionary
class GPUSamplerDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        addressModeU: str = "clamp-to-edge",
        addressModeV: str = "clamp-to-edge",
        addressModeW: str = "clamp-to-edge",
        compare: str | None = None,
        label: str = "",
        lodMaxClamp: float = 32,
        lodMinClamp: float = 0,
        magFilter: str = "nearest",
        maxAnisotropy: int = 1,
        minFilter: str = "nearest",
        mipmapFilter: str = "nearest",
    ):
        self.addressModeU = addressModeU
        self.addressModeV = addressModeV
        self.addressModeW = addressModeW
        if compare is not None:
            self.compare = compare
        self.label = label
        self.lodMaxClamp = lodMaxClamp
        self.lodMinClamp = lodMinClamp
        self.magFilter = magFilter
        self.maxAnisotropy = maxAnisotropy
        self.minFilter = minFilter
        self.mipmapFilter = mipmapFilter


@js.dictionary
class GPURenderPassLayout:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        colorFormats: list[str | None],
        depthStencilFormat: str | None = None,
        label: str = "",
        sampleCount: int = 1,
    ):
        self.colorFormats = colorFormats
        if depthStencilFormat is not None:
            self.depthStencilFormat = depthStencilFormat
        self.label = label
        self.sampleCount = sampleCount


@js.dictionary
class GPUExternalTextureDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        source: HTMLVideoElement | VideoFrame,
        colorSpace: str = "srgb",
        label: str = "",
    ):
        self.source = source
        self.colorSpace = colorSpace
        self.label = label


@js.dictionary
class GPUComputePassDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        label: str = "",
        timestampWrites: GPUComputePassTimestampWrites | None = None,
    ):
        self.label = label
        if timestampWrites is not None:
            self.timestampWrites = timestampWrites


@js.dictionary
class GPUCommandEncoderDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, label: str = ""):
        self.label = label


@js.dictionary
class GPUCommandBufferDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, label: str = ""):
        self.label = label


@js.dictionary
class GPUBindGroupLayoutDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, entries: list[GPUBindGroupLayoutEntry], label: str = ""):
        self.entries = entries
        self.label = label


@js.dictionary
class GPUBindGroupDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        layout: GPUBindGroupLayout,
        entries: list[GPUBindGroupEntry],
        label: str = "",
    ):
        self.layout = layout
        self.entries = entries
        self.label = label


@js.dictionary
class GPUPipelineDescriptorBase:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, layout: GPUPipelineLayout | str, label: str = ""):
        self.layout = layout
        self.label = label


@js.dictionary
class GPUPipelineLayoutDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        bindGroupLayouts: list[GPUBindGroupLayout | None],
        immediateSize: int = 0,
        label: str = "",
    ):
        self.bindGroupLayouts = bindGroupLayouts
        self.immediateSize = immediateSize
        self.label = label


@js.dictionary
class GPUQuerySetDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, count: int, type: str, label: str = ""):
        self.count = count
        self.type = type
        self.label = label


@js.dictionary
class GPUQueueDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, label: str = ""):
        self.label = label


@js.dictionary
class GPURenderBundleDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(self, label: str = ""):
        self.label = label


@js.dictionary
class GPURenderPassDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        color_attachments: list[GPURenderPassColorAttachment | None],
        depth_stencil_attachment: GPURenderPassDepthStencilAttachment | None = None,
        label: str = "",
        *,
        maxDrawCount: int = 50000000,
        occlusionQuerySet: GPUQuerySet | None = None,
        timestampWrites: GPURenderPassTimestampWrites | None = None,
    ):
        self.colorAttachments = color_attachments
        if depth_stencil_attachment is not None:
            self.depthStencilAttachment = depth_stencil_attachment
        self.label = label
        self.maxDrawCount = maxDrawCount
        if occlusionQuerySet is not None:
            self.occlusionQuerySet = occlusionQuerySet
        if timestampWrites is not None:
            self.timestampWrites = timestampWrites


@js.dictionary
class GPUTexelCopyBufferInfo:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        buffer: GPUBuffer,
        bytesPerRow: int | None = None,
        offset: int = 0,
        rowsPerImage: int | None = None,
    ):
        self.buffer = buffer
        if bytesPerRow is not None:
            self.bytesPerRow = bytesPerRow
        self.offset = offset
        if rowsPerImage is not None:
            self.rowsPerImage = rowsPerImage


@js.dictionary
class GPUCopyExternalImageDestInfo:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        texture: GPUTexture,
        aspect: str = "all",
        colorSpace: str = "srgb",
        mipLevel: int = 0,
        origin: list[int] | GPUOrigin3DDict | None = None,
        premultipliedAlpha: bool = False,
    ):
        self.texture = texture
        self.aspect = aspect
        self.colorSpace = colorSpace
        self.mipLevel = mipLevel
        if origin is None:
            origin = list[int]()
        self.origin = origin
        self.premultipliedAlpha = premultipliedAlpha


@js.dictionary
class GPURenderBundleEncoderDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        colorFormats: list[str | None],
        depthReadOnly: bool = False,
        depthStencilFormat: str | None = None,
        label: str = "",
        sampleCount: int = 1,
        stencilReadOnly: bool = False,
    ):
        self.colorFormats = colorFormats
        self.depthReadOnly = depthReadOnly
        if depthStencilFormat is not None:
            self.depthStencilFormat = depthStencilFormat
        self.label = label
        self.sampleCount = sampleCount
        self.stencilReadOnly = stencilReadOnly


@js.dictionary
class GPURenderPipelineDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        vertex: GPUVertexState,
        fragment: GPUFragmentState | None,
        primitive: GPUPrimitiveState | None,
        depth_stencil: GPUDepthStencilState | None = None,
        layout: GPUPipelineLayout | str = "auto",
        label: str = "",
        *,
        multisample: GPUMultisampleState | None = None,
    ):
        self.vertex = vertex
        self.fragment = fragment
        self.primitive = primitive
        if depth_stencil is not None:
            self.depthStencil = depth_stencil
        self.layout = layout
        self.label = label
        if multisample is None:
            multisample = GPUMultisampleState()
        self.multisample = multisample


@js.dictionary
class GPUComputePipelineDescriptor:
    """WebIDL source: @webref/idl/webgpu.idl"""

    def __init__(
        self,
        compute: GPUProgrammableStage,
        layout: GPUPipelineLayout | str,
        label: str = "",
    ):
        self.compute = compute
        self.layout = layout
        self.label = label


@js.native
class GPUValidationError(GPUError):
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUValidationError

    Browser support: Chrome 144, Safari 26"""

    def __init__(self, message: str):
        super().__init__()


@js.native
class GPUInternalError(GPUError):
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUInternalError

    Browser support: Chrome 144, Safari 26"""

    def __init__(self, message: str):
        super().__init__()


@js.native
class GPUOutOfMemoryError(GPUError):
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUOutOfMemoryError

    Browser support: Chrome 144, Safari 26"""

    def __init__(self, message: str):
        super().__init__()


@js.inline("{canvas}.getContext('webgpu')")
def get_webgpu_context(canvas: HTMLCanvasElement) -> GPUCanvasContext: ...
