"""Call-local text output, JSON indentation and Python/JSON escaping."""

from functools import cache

from pyjs import int8, int32

from .algorithms import _positive_quotient, _runtime
from .arena import BUFFER_DATA_OFFSET
from .buffers import (
    CAPACITY_OFFSET,
    DATA_OFFSET,
    DESCRIPTOR_OFFSET,
    ERROR_OFFSET,
    LENGTH_OFFSET,
    OWNER_OFFSET,
    STRING_DATA_OFFSET,
    append_bytes,
    reserve_memory,
)
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    free,
    is_null,
    load_int32,
    load_integer,
    load_pointer,
    null,
    store_int8,
    store_int32,
    store_integer,
    store_pointer,
)
from .text_operations import new_owned


@_runtime
def initialize(output: Pointer, owner: Pointer) -> None:
    # Call-local records, not arena-linked buffers. Only the growing byte
    # payload is malloc-backed, and every normal/error exit releases it.
    store_pointer(output, null())
    store_pointer(byte_offset(output, DATA_OFFSET), null())
    store_integer(byte_offset(output, LENGTH_OFFSET), 0)
    store_integer(byte_offset(output, CAPACITY_OFFSET), 0)
    store_int32(byte_offset(output, DESCRIPTOR_OFFSET), int32(-1))
    store_int32(byte_offset(output, ERROR_OFFSET), int32(0))
    store_pointer(byte_offset(output, OWNER_OFFSET), owner)
    store_pointer(owner, null())
    store_pointer(byte_offset(owner, BUFFER_DATA_OFFSET), null())


@_runtime
def finish(output: Pointer, arena: Pointer, allocator: Pointer, context: Pointer) -> Pointer:
    if load_int32(byte_offset(output, ERROR_OFFSET)) != int32(0):
        return null()
    length = load_integer(byte_offset(output, LENGTH_OFFSET))
    result = new_owned(arena, allocator, context, length)
    if not is_null(result):
        copy(load_pointer(byte_offset(result, STRING_DATA_OFFSET)),
             load_pointer(byte_offset(output, DATA_OFFSET)), length)
    return result


@_runtime
def destroy(output: Pointer) -> None:
    free(load_pointer(byte_offset(output, DATA_OFFSET)))
    store_pointer(byte_offset(output, DATA_OFFSET), null())
    owner = load_pointer(byte_offset(output, OWNER_OFFSET))
    store_pointer(byte_offset(owner, BUFFER_DATA_OFFSET), null())


@_runtime
def indent(output: Pointer, token: Pointer, count: int, depth: int) -> None:
    if load_int32(byte_offset(output, ERROR_OFFSET)) != int32(0):
        return
    # None disables formatting; a present empty token still emits a newline.
    if is_null(token):
        return
    size = load_integer(token)
    length = load_integer(byte_offset(output, LENGTH_OFFSET))
    if length < 0 or length == 9223372036854775807 or count < 0 or depth < 0 or size < 0:
        store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
        return
    # Empty indentation still emits a newline. Check products before allocation.
    if size == 0 or count == 0 or depth == 0:
        amount = 0
    else:
        if count > _positive_quotient(9223372036854775807, depth):
            store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
            return
        amount = count * depth
        if amount > _positive_quotient(9223372036854775806 - length, size):
            store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
            return
    required = length + 1 + amount * size
    data = reserve_memory(output, required)
    if is_null(data):
        return
    store_int8(byte_offset(data, length), int8(10))
    position = length + 1
    source = load_pointer(byte_offset(token, STRING_DATA_OFFSET))
    index = 0
    while index < amount:
        copy(byte_offset(data, position), source, size)
        position += size
        index += 1
    store_integer(byte_offset(output, LENGTH_OFFSET), required)


@cache
def compiled_runtime():
    from .compiler import compile_runtime
    from .escaping import write_json, write_repr

    return compile_runtime({"pyjs.json.write.string": write_json, "pyjs.repr.write.string": write_repr, "pyjs.json.indent": indent,
                            "pyjs.text.output.initialize": initialize, "pyjs.text.output.finish": finish,
                            "pyjs.text.output.destroy": destroy}, dependencies={
        "pyjs.native.output.append.bytes": append_bytes,
        "pyjs.native.output.reserve.memory": reserve_memory,
        "pyjs.string.new.owned": new_owned,
    })
