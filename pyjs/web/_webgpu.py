import re

from pyjs import js
from pyjs.javascript import TypedArray, typed_array_bytes


@js.native
def snake(name: str) -> str:
    return re.sub("([A-Z])", lambda match: "_" + match.group(1).lower(), name)


@js.native
def lower(value: object) -> object:
    native = getattr(value, "_native", None)
    if native is not None:
        return native
    if isinstance(value, (str, bytes, bool, int, float)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [lower(item) for item in value]
    if isinstance(value, dict):
        # A plain dict is a WebIDL record -- constants, for one -- whose keys
        # are user data, not member names. Only attributes get case-mapped.
        return {key: lower(item) for key, item in value.items()}
    if hasattr(value, "__dict__"):
        return {
            snake(key): lower(item)
            for key, item in vars(value).items()
            if item is not None and (not key.startswith("_"))
        }
    return value


@js.native
def typed_bytes(data: object) -> object:
    if hasattr(data, "byteOffset"):
        return typed_array_bytes(data)
    raw = getattr(data, "_bytes", None)
    if raw is not None:
        return bytes(raw)
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError(f"cannot read bytes from {type(data).__name__}")


@js.native
def buffer_source_bytes(
    data: object,
    data_offset: int = 0,
    size: int | None = None,
) -> object:
    """Apply element-based offsets before passing bytes to wgpu-py."""
    if data_offset < 0 or (size is not None and size < 0):
        raise ValueError("buffer source offset and size cannot be negative")
    raw = typed_bytes(data)
    element_size = data._size if isinstance(data, TypedArray) else 1
    start = data_offset * element_size
    stop = len(raw) if size is None else start + size * element_size
    if start > len(raw) or stop > len(raw):
        raise ValueError("buffer source range is outside the supplied data")
    return raw[start:stop]


@js.native
def request_adapter(
    feature_level: str,
    power_preference: str | None,
    force_fallback_adapter: bool,
) -> object:
    import wgpu

    return wgpu.gpu.request_adapter_sync(
        feature_level=feature_level,
        power_preference=power_preference,
        force_fallback_adapter=force_fallback_adapter,
    )


@js.native
def wrap(cls: object, native: object, **attributes: object) -> object:
    obj = cls()
    obj._native = native
    for key, value in attributes.items():
        setattr(obj, key, value)
    return obj
