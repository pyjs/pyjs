"""Copy borrowed concrete input graphs before entering managed application code.

Shapes describe layout, not Python behavior. Copying cannot call user code or
collect: the caller publishes all copied roots before its first safe point.
One identity map spans every argument, including otherwise read-only aliases.
"""

import ctypes
from functools import cache

from .algorithms import _positive_quotient, _runtime
from .arena import allocate_in_arena
from .collector import build_index_in, find
from .heap import HEAP_INDEX_OFFSET, HEAP_SIZE, allocate_described
from .identity import get, put
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    is_null,
    load_bool,
    load_integer,
    load_pointer,
    null,
    store_integer,
    store_pointer,
)
from .text_operations import STRING_DATA_OFFSET


class _Shape(ctypes.Structure):
    _fields_ = [("size", ctypes.c_int64), ("count", ctypes.c_int64),
                ("fields", ctypes.c_void_p), ("allocator", ctypes.c_int64),
                ("inline", ctypes.c_bool), ("identity", ctypes.c_void_p),
                ("extra_allocator", ctypes.c_int64), ("descriptor", ctypes.c_void_p),
                ("item_allocator", ctypes.c_void_p), ("extra_item_allocator", ctypes.c_void_p),
                ("text", ctypes.c_bool)]


class _Field(ctypes.Structure):
    _fields_ = [("offset", ctypes.c_int64), ("shape", ctypes.c_void_p),
                ("count_offset", ctypes.c_int64), ("stride", ctypes.c_int64),
                ("optional", ctypes.c_bool), ("tag", ctypes.c_int64),
                ("descriptor", ctypes.c_void_p)]


FIELD_SIZE = ctypes.sizeof(_Field)
SHAPE_COUNT = _Shape.count.offset
SHAPE_FIELDS = _Shape.fields.offset
SHAPE_ALLOCATOR = _Shape.allocator.offset
SHAPE_INLINE = _Shape.inline.offset
SHAPE_IDENTITY = _Shape.identity.offset
SHAPE_EXTRA_ALLOCATOR = _Shape.extra_allocator.offset
SHAPE_DESCRIPTOR = _Shape.descriptor.offset
SHAPE_ITEM_ALLOCATOR = _Shape.item_allocator.offset
SHAPE_EXTRA_ITEM_ALLOCATOR = _Shape.extra_item_allocator.offset
SHAPE_TEXT = _Shape.text.offset
FIELD_SHAPE = _Field.shape.offset
FIELD_COUNT = _Field.count_offset.offset
FIELD_STRIDE = _Field.stride.offset
FIELD_OPTIONAL = _Field.optional.offset
FIELD_TAG = _Field.tag.offset
FIELD_DESCRIPTOR = _Field.descriptor.offset

# The work queue owns two pointers (pending/free). Each reusable frame holds
# next/source/target/shape. No object depth consumes the Python or native stack.
WORK_SIZE = 32


@_runtime
def ownership_snapshot(arena: Pointer, heap: Pointer, check_owned: bool) -> Pointer:
    if not check_owned:
        return heap  # Non-null success sentinel; the caller skips lookup.
    snapshot = allocate_in_arena(arena, HEAP_SIZE, 8)
    if is_null(snapshot):
        return null()
    # Only find() consumes this read-only heap view. Its allocation head/count
    # must not include copies allocated during promotion. No collection or user
    # callbacks run until promotion ends. The wrapper clears its scratch arena
    # before application entry (or on failure); the real GC index is untouched.
    copy(snapshot, heap, HEAP_SIZE)
    store_pointer(byte_offset(snapshot, HEAP_INDEX_OFFSET), null())
    return snapshot if build_index_in(snapshot, arena) else null()


@_runtime
def promote(arena: Pointer, heap: Pointer, memo: Pointer, source: Pointer,
            shape: Pointer, allocator: Pointer, owned: Pointer) -> Pointer:
    work = allocate_in_arena(arena, 16, 8)
    if is_null(work):
        return null()
    store_pointer(work, null())
    store_pointer(byte_offset(work, 8), null())
    result = promote_object(arena, heap, memo, source, shape, owned, work)
    if is_null(result):
        return null()
    while not is_null(load_pointer(work)):
        frame = load_pointer(work)
        store_pointer(work, load_pointer(frame))
        original = load_pointer(byte_offset(frame, 8))
        target = load_pointer(byte_offset(frame, 16))
        layout = load_pointer(byte_offset(frame, 24))
        # All frame values are now locals, so nested work can reuse the frame.
        store_pointer(frame, load_pointer(byte_offset(work, 8)))
        store_pointer(byte_offset(work, 8), frame)
        if not promote_fields(arena, heap, memo, original, target, layout, allocator, owned, work):
            return null()
    return result


@_runtime
def enqueue_fields(arena: Pointer, work: Pointer, source: Pointer,
                   result: Pointer, shape: Pointer) -> bool:
    frame = load_pointer(byte_offset(work, 8))
    if is_null(frame):
        frame = allocate_in_arena(arena, WORK_SIZE, 8)
        if is_null(frame):
            return False
    else:
        store_pointer(byte_offset(work, 8), load_pointer(frame))
    store_pointer(frame, load_pointer(work))
    store_pointer(byte_offset(frame, 8), source)
    store_pointer(byte_offset(frame, 16), result)
    store_pointer(byte_offset(frame, 24), shape)
    store_pointer(work, frame)
    return True


@_runtime
def promote_object(arena: Pointer, heap: Pointer, memo: Pointer, source: Pointer,
                   shape: Pointer, owned: Pointer, work: Pointer) -> Pointer:
    if is_null(source):
        return null()
    # Mixed raw callers can nest already-owned objects inside borrowed parents.
    # Preserve those identities at every depth, not just for direct roots.
    if not is_null(owned) and not is_null(find(owned, source)):
        return source
    previous = get(memo, source)
    if not is_null(previous):
        return previous
    size = load_integer(shape)
    text = load_bool(byte_offset(shape, SHAPE_TEXT))
    length = load_integer(source) if text else 0
    if text and (length < 0 or length > 9223372036854775807 - size):
        return null()
    data = load_pointer(byte_offset(source, STRING_DATA_OFFSET)) if text else null()
    if length != 0 and is_null(data):
        return null()
    allocation = size + length
    result = allocate_described(heap, allocation if allocation else 1, load_pointer(byte_offset(shape, SHAPE_DESCRIPTOR)))
    if is_null(result):
        return null()
    copy(result, source, size)
    if text:
        # Empty strings still own the header. Their one-past data pointer is
        # never dereferenced; nonempty bytes share this allocation and lifetime.
        target = byte_offset(result, size)
        if length:
            copy(target, data, length)
        store_pointer(byte_offset(result, STRING_DATA_OFFSET), target)
    identity = load_pointer(byte_offset(shape, SHAPE_IDENTITY))
    if not is_null(identity):
        # Borrowed headers are untrusted placeholders. Install only the identity
        # from this library's shape, without modifying the caller's snapshot.
        # Already-owned objects returned above retain their real dynamic type.
        store_pointer(result, identity)
    if not put(arena, memo, source, result):
        return null()
    return result if text or enqueue_fields(arena, work, source, result, shape) else null()


@_runtime
def promote_fields(arena: Pointer, heap: Pointer, memo: Pointer, source: Pointer,
                   result: Pointer, shape: Pointer, allocator: Pointer, owned: Pointer, work: Pointer) -> bool:
    """Rewrite references in an already-copied object or inline tagged slot.

    Tagged scalar bits are never pointers. A nonzero field tag selects the
    single reference payload described by that arm; zero means unconditional.
    Inline slots need no separate allocation or identity-map entry.
    """
    allocator_offset = load_integer(byte_offset(shape, SHAPE_ALLOCATOR))
    if allocator_offset >= 0:
        # Only initialized entries are copied, not spare foreign capacity.
        # Both supported mutable headers begin with length and capacity.
        store_integer(byte_offset(result, 8), load_integer(source))
        # Raw callers may omit typed callbacks and keep the supplied fallback.
        # Compiled shapes describe future growth as well as this first copy.
        primary = load_pointer(byte_offset(shape, SHAPE_ITEM_ALLOCATOR))
        store_pointer(byte_offset(result, allocator_offset), allocator if is_null(primary) else primary)
        store_pointer(byte_offset(result, allocator_offset + 8), heap)
        # Mapping values have their own callback. Zero means no secondary
        # allocator; mutable headers always begin with length/capacity, not it.
        extra = load_integer(byte_offset(shape, SHAPE_EXTRA_ALLOCATOR))
        if extra:
            secondary = load_pointer(byte_offset(shape, SHAPE_EXTRA_ITEM_ALLOCATOR))
            store_pointer(byte_offset(result, extra), allocator if is_null(secondary) else secondary)
    fields = load_pointer(byte_offset(shape, SHAPE_FIELDS))
    index = 0
    while index < load_integer(byte_offset(shape, SHAPE_COUNT)):
        field = byte_offset(fields, index * FIELD_SIZE)
        tag = load_integer(byte_offset(field, FIELD_TAG))
        if tag != 0 and tag != load_integer(source):
            index += 1
            continue
        offset = load_integer(field)
        child_shape = load_pointer(byte_offset(field, FIELD_SHAPE))
        count_offset = load_integer(byte_offset(field, FIELD_COUNT))
        inline = not is_null(child_shape) and load_bool(byte_offset(child_shape, SHAPE_INLINE))
        if count_offset < 0 and inline:
            if not enqueue_fields(arena, work, byte_offset(source, offset), byte_offset(result, offset), child_shape):
                return False
            index += 1
            continue
        child = load_pointer(byte_offset(source, offset))
        created = null()
        if count_offset < 0:
            if not is_null(child):
                created = promote_object(arena, heap, memo, child, child_shape, owned, work)
                if is_null(created):
                    return False
        else:
            count = load_integer(byte_offset(source, count_offset))
            stride = load_integer(byte_offset(field, FIELD_STRIDE))
            if count < 0 or stride <= 0 or count > _positive_quotient(9223372036854775807, stride):
                return False
            # Lazy mapping insertion-order buffers may be absent even for
            # nonempty mappings; ordinary string/collection buffers may not.
            if count > 0 and is_null(child) and not load_bool(byte_offset(field, FIELD_OPTIONAL)):
                return False
            if not is_null(child):
                size = count * stride
                created = allocate_described(heap, size if size else 1, load_pointer(byte_offset(field, FIELD_DESCRIPTOR)))
                if is_null(created):
                    return False
                copy(created, child, count * stride)
                if not is_null(child_shape):
                    item = 0
                    while item < count:
                        source_slot = byte_offset(child, item * stride)
                        target_slot = byte_offset(created, item * stride)
                        if inline:
                            if not enqueue_fields(arena, work, source_slot, target_slot, child_shape):
                                return False
                        else:
                            original = load_pointer(source_slot)
                            value = promote_object(arena, heap, memo, original, child_shape, owned, work)
                            if not is_null(original) and is_null(value):
                                return False
                            store_pointer(target_slot, value)
                        item += 1
        store_pointer(byte_offset(result, offset), created)
        index += 1
    return True


@cache
def compiled_runtime():
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.input.try.ownership": ownership_snapshot,
                            "pyjs.input.try.copy": promote}, dependencies={
        "pyjs.arena.try.alloc": allocate_in_arena,
        "pyjs.gc.try.index": build_index_in,
        "pyjs.gc.try.alloc.described": allocate_described,
        "pyjs.gc.find": find,
        "pyjs.identity.get": get,
        "pyjs.identity.try.put": put,
    })
