"""List storage shared by collection construction and text splitting."""

import ctypes
from functools import cache

from pyjs import int8
from pyjs.decorators import native_operation

from .algorithms import _positive_quotient, _runtime, slice_bound
from .arena import allocate_collection
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    fill,
    is_null,
    load_int8,
    load_integer,
    load_pointer,
    move,
    null,
    same_address,
    store_int8,
    store_integer,
    store_pointer,
    trap,
)
from .values import key_equal


class _List(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int64), ("capacity", ctypes.c_int64),
                ("items", ctypes.c_void_p), ("allocator", ctypes.c_void_p),
                ("context", ctypes.c_void_p), ("hash_cache", ctypes.c_int64)]


SIZE = ctypes.sizeof(_List)
CAPACITY = _List.capacity.offset
ITEMS_OFFSET = _List.items.offset
ALLOCATOR = _List.allocator.offset
CONTEXT = _List.context.offset
HASH_CACHE = _List.hash_cache.offset
TUPLE_DATA = 48


@native_operation("memory.collection.header")
def allocate_header(arena: Pointer, allocator: Pointer, context: Pointer, size: int) -> Pointer:
    # The payload owner can be atomic, but the header always owns its items.
    # Native lowering recognizes GC callbacks; foreign callbacks keep their ABI.
    return allocate_collection(arena, allocator, context, size)


@_runtime
def trace_tuple(value: Pointer, index: int) -> Pointer:
    offset = index * 8
    # The collector bounds index by allocation size. Header pointers are all
    # internal/immortal; cached hashes and lengths must never retain objects.
    return null() if offset < TUPLE_DATA else load_pointer(byte_offset(value, offset))


@native_operation("memory.tuple.header")
def allocate_tuple_header(arena: Pointer, allocator: Pointer, context: Pointer, size: int) -> Pointer:
    return allocate_collection(arena, allocator, context, size)


@_runtime
def new_tuple(arena: Pointer, allocator: Pointer, context: Pointer, size: int, length: int) -> Pointer:
    # Immutable payloads share the list header but need no spare capacity.
    # One allocation keeps row production atomic before iterator advancement.
    if size < 0 or size > 9223372036854775807 - TUPLE_DATA:
        return null()
    result = allocate_tuple_header(arena, allocator, context, TUPLE_DATA + size)
    if is_null(result):
        return null()
    fill(result, int8(0), TUPLE_DATA + size)
    store_integer(result, length)
    store_integer(byte_offset(result, CAPACITY), length)
    store_pointer(byte_offset(result, ITEMS_OFFSET), byte_offset(result, TUPLE_DATA))
    store_pointer(byte_offset(result, ALLOCATOR), allocator)
    store_pointer(byte_offset(result, CONTEXT), context)
    return result


@_runtime
def try_new_list(arena: Pointer, allocator: Pointer, context: Pointer, item_size: int, length: int) -> Pointer:
    capacity = 4 if length < 4 else length
    if length < 0 or item_size <= 0 or capacity > _positive_quotient(9223372036854775807, item_size):
        return null()
    result = allocate_header(arena, allocator, context, SIZE)
    if is_null(result):
        return null()
    store_integer(result, 0)
    store_integer(byte_offset(result, CAPACITY), 0)
    store_pointer(byte_offset(result, ITEMS_OFFSET), null())
    store_pointer(byte_offset(result, ALLOCATOR), allocator)
    store_pointer(byte_offset(result, CONTEXT), context)
    store_integer(byte_offset(result, HASH_CACHE), 0)
    data = allocate_collection(arena, allocator, context, capacity * item_size)
    if is_null(data):
        return null()
    store_pointer(byte_offset(result, ITEMS_OFFSET), data)
    store_integer(byte_offset(result, CAPACITY), capacity)
    store_integer(result, length)
    return result


@_runtime
def new_list(arena: Pointer, allocator: Pointer, context: Pointer, item_size: int, length: int) -> Pointer:
    return try_new_list(arena, allocator, context, item_size, length)


@_runtime
def allocate_data(arena: Pointer, value: Pointer, size: int) -> Pointer:
    return allocate_collection(arena, load_pointer(byte_offset(value, ALLOCATOR)),
                               load_pointer(byte_offset(value, CONTEXT)), size)


@_runtime
def require(value: Pointer) -> Pointer:
    if is_null(value):
        trap()
    return value


@_runtime
def append_required(arena: Pointer, value: Pointer, item_size: int) -> Pointer:
    return append_slot(arena, value, item_size)


@_runtime
def reverse(value: Pointer, item_size: int) -> None:
    length = load_integer(value)
    data = load_pointer(byte_offset(value, ITEMS_OFFSET))
    index = 0
    while index < _positive_quotient(length, 2):
        left = byte_offset(data, index * item_size)
        right = byte_offset(data, (length - index - 1) * item_size)
        offset = 0
        while offset < item_size:
            saved = load_int8(byte_offset(left, offset))
            store_int8(byte_offset(left, offset), load_int8(byte_offset(right, offset)))
            store_int8(byte_offset(right, offset), saved)
            offset += 1
        index += 1


@_runtime
def get(value: Pointer, index: int, item_size: int) -> Pointer:
    length = load_integer(value)
    actual = index + length if index < 0 else index
    if actual < 0 or actual >= length:
        trap()
    return byte_offset(load_pointer(byte_offset(value, ITEMS_OFFSET)), actual * item_size)


@_runtime
def reserve(arena: Pointer, value: Pointer, required: int, item_size: int) -> bool:
    capacity = load_integer(byte_offset(value, CAPACITY))
    following = growth_capacity(capacity, required, item_size, 0)
    if following < 0:
        return False
    if required > capacity:
        data = allocate_data(arena, value, following * item_size)
        if is_null(data):
            return False
        copy(data, load_pointer(byte_offset(value, ITEMS_OFFSET)), load_integer(value) * item_size)
        store_pointer(byte_offset(value, ITEMS_OFFSET), data)
        store_integer(byte_offset(value, CAPACITY), following)
    return True


@_runtime
def append_slot(arena: Pointer, value: Pointer, item_size: int) -> Pointer:
    length = load_integer(value)
    capacity = load_integer(byte_offset(value, CAPACITY))
    if length == capacity:
        following = append_capacity(capacity, item_size)
        if following < 0 or not reserve(arena, value, following, item_size):
            return null()
    # Caller must initialize this slot before any callback or GC safepoint.
    slot = byte_offset(load_pointer(byte_offset(value, ITEMS_OFFSET)), length * item_size)
    store_integer(value, length + 1)
    return slot


@_runtime
def reserve_extension(arena: Pointer, target: Pointer, count: int, item_size: int) -> bool:
    length = load_integer(target)
    if count < 0 or count > 9223372036854775807 - length:
        return False
    return reserve(arena, target, length + count, item_size)


@_runtime
def extend(arena: Pointer, target: Pointer, source: Pointer, item_size: int) -> bool:
    source_length = load_integer(source)
    if source_length == 0:
        return True
    length = load_integer(target)
    # Snapshot before reserve/publication: self-extension repeats only the
    # original prefix. The allocator cannot collect or invoke application code.
    source_data = load_pointer(byte_offset(source, ITEMS_OFFSET))
    if not reserve_extension(arena, target, source_length, item_size):
        return False
    data = load_pointer(byte_offset(target, ITEMS_OFFSET))
    copy(byte_offset(data, length * item_size), source_data, source_length * item_size)
    store_integer(target, length + source_length)
    return True


@_runtime
def repeat(arena: Pointer, target: Pointer, source: Pointer, item_size: int, length: int) -> bool:
    if length == 0:
        truncate(target, 0, item_size)
        return True
    source_length = load_integer(source)
    if same_address(source, target) and source_length == length:
        return True
    if item_size <= 0 or source_length <= 0 or length < source_length:
        return False
    if length > _positive_quotient(9223372036854775807, item_size):
        return False
    size = length * item_size
    data = allocate_data(arena, target, size)
    if is_null(data):
        return False
    copied = source_length * item_size
    copy(data, load_pointer(byte_offset(source, ITEMS_OFFSET)), copied)
    while copied < size:
        amount = copied if copied < size - copied else size - copied
        copy(byte_offset(data, copied), data, amount)
        copied += amount
    # Publish only the fully copied replacement, including self-repetition.
    store_pointer(byte_offset(target, ITEMS_OFFSET), data)
    store_integer(byte_offset(target, CAPACITY), length)
    store_integer(target, length)
    return True


@_runtime
def slice_count(first: int, limit: int, stride: int) -> int:
    if stride == 0:
        trap()
    distance = limit - first if stride > 0 else first - limit
    if distance <= 0:
        return 0
    # Normalized list bounds are [-1, length], so distance fits signed i64.
    # Rearranging ceil(distance / abs(stride)) avoids both rounding overflow
    # and abs(INT64_MIN); that extreme stride can select only one item.
    if stride == -9223372036854775808:
        return 1
    width = stride if stride > 0 else -stride
    return _positive_quotient(distance - 1, width) + 1


@_runtime
def slice_length(length: int, start: int, start_present: bool, stop: int, stop_present: bool,
                 step: int, step_present: bool) -> int:
    stride = step if step_present else 1
    reverse = stride < 0
    first = slice_bound(length, start, reverse) if start_present else length - 1 if reverse else 0
    limit = slice_bound(length, stop, reverse) if stop_present else -1 if reverse else length
    return slice_count(first, limit, stride)


@_runtime
def slice_copy(arena: Pointer, allocator: Pointer, context: Pointer, source: Pointer, item_size: int,
               start: int, start_present: bool, stop: int, stop_present: bool,
               step: int, step_present: bool) -> Pointer:
    stride = step if step_present else 1
    length = load_integer(source)
    reverse = stride < 0
    first = slice_bound(length, start, reverse) if start_present else length - 1 if reverse else 0
    limit = slice_bound(length, stop, reverse) if stop_present else -1 if reverse else length
    count = slice_count(first, limit, stride)
    result = new_list(arena, allocator, context, item_size, count)
    if is_null(result):
        return null()
    data = load_pointer(byte_offset(source, ITEMS_OFFSET))
    target = load_pointer(byte_offset(result, ITEMS_OFFSET))
    index = 0
    position = first
    while index < count:
        copy(byte_offset(target, index * item_size), byte_offset(data, position * item_size), item_size)
        index += 1
        # The terminal index+stride need not fit. Only compute live indexes.
        if index < count:
            position += stride
    return result


@_runtime
def slice_tuple(arena: Pointer, allocator: Pointer, context: Pointer, source: Pointer, item_size: int,
                start: int, start_present: bool, stop: int, stop_present: bool,
                step: int, step_present: bool) -> Pointer:
    length = load_integer(source)
    # Lowering validates/coerces the stride before entering this helper. An
    # empty immutable tuple needs no copy even for a non-unit/negative stride.
    if length == 0:
        return source
    if (not step_present or step == 1) and slice_length(
        length, start, start_present, stop, stop_present, step, step_present,
    ) == length:
        return source
    return slice_copy(arena, allocator, context, source, item_size,
                      start, start_present, stop, stop_present, step, step_present)


@_runtime
def assign_extended_slice(arena: Pointer, value: Pointer, replacement: Pointer, item_size: int,
                          start: int, start_present: bool, stop: int, stop_present: bool, stride: int) -> bool:
    length = load_integer(value)
    reverse = stride < 0
    first = slice_bound(length, start, reverse) if start_present else length - 1 if reverse else 0
    limit = slice_bound(length, stop, reverse) if stop_present else -1 if reverse else length
    count = slice_count(first, limit, stride)
    # Check the replacement size before any write; errors must not leave a
    # partially edited list. Application lowering checks shape before calling.
    if count != load_integer(replacement):
        trap()
    snapshot = try_new_list(arena, load_pointer(byte_offset(value, ALLOCATOR)),
                        load_pointer(byte_offset(value, CONTEXT)), item_size, count)
    if is_null(snapshot):
        return False
    source = load_pointer(byte_offset(snapshot, ITEMS_OFFSET))
    copy(source, load_pointer(byte_offset(replacement, ITEMS_OFFSET)), count * item_size)
    data = load_pointer(byte_offset(value, ITEMS_OFFSET))
    index = 0
    position = first
    while index < count:
        copy(byte_offset(data, position * item_size), byte_offset(source, index * item_size), item_size)
        index += 1
        if index < count:
            position += stride
    return True


@_runtime
def assign_slice(arena: Pointer, value: Pointer, replacement: Pointer, item_size: int,
                 start: int, start_present: bool, stop: int, stop_present: bool,
                 step: int, step_present: bool) -> bool:
    stride = step if step_present else 1
    if stride != 1:
        return assign_extended_slice(arena, value, replacement, item_size, start, start_present, stop, stop_present, stride)
    length = load_integer(value)
    first = slice_bound(length, start, False) if start_present else 0
    limit = slice_bound(length, stop, False) if stop_present else length
    if limit < first:
        limit = first
    replacement_length = load_integer(replacement)
    if first == limit and replacement_length == 0:
        return True
    kept = length - (limit - first)
    if replacement_length > 9223372036854775807 - kept:
        return False
    following = kept + replacement_length
    result = try_new_list(arena, load_pointer(byte_offset(value, ALLOCATOR)),
                      load_pointer(byte_offset(value, CONTEXT)), item_size, following)
    if is_null(result):
        return False
    data = load_pointer(byte_offset(value, ITEMS_OFFSET))
    source = load_pointer(byte_offset(replacement, ITEMS_OFFSET))
    target = load_pointer(byte_offset(result, ITEMS_OFFSET))
    copy(target, data, first * item_size)
    copy(byte_offset(target, first * item_size), source, replacement_length * item_size)
    copy(byte_offset(target, (first + replacement_length) * item_size),
         byte_offset(data, limit * item_size), (length - limit) * item_size)
    store_pointer(byte_offset(value, ITEMS_OFFSET), target)
    store_integer(byte_offset(value, CAPACITY), load_integer(byte_offset(result, CAPACITY)))
    store_integer(value, following)
    return True


@_runtime
def insert(arena: Pointer, value: Pointer, index: int, item: Pointer, item_size: int) -> bool:
    length = load_integer(value)
    actual = slice_bound(length, index, False)
    slot = append_slot(arena, value, item_size)
    if is_null(slot):
        return False
    target = byte_offset(load_pointer(byte_offset(value, ITEMS_OFFSET)), actual * item_size)
    move(byte_offset(target, item_size), target, (length - actual) * item_size)
    # Lowering supplies a private value slot, not a pointer into this list.
    copy(target, item, item_size)
    return True


@_runtime
def growth_capacity(capacity: int, required: int, item_size: int, minimum: int) -> int:
    if capacity < 0 or required < 0 or item_size < 0 or minimum < 0:
        return -1
    maximum = 9223372036854775807
    if item_size:
        maximum = _positive_quotient(maximum, item_size)
    if capacity > maximum or required > maximum:
        return -1
    # Keep geometric growth when its byte size fits. Near the limit, requesting
    # just the needed capacity can still succeed; never wrap before checking.
    preferred = capacity * 2 if capacity <= maximum - capacity else required
    if preferred < minimum:
        preferred = minimum
    if preferred > maximum:
        preferred = required
    return required if preferred < required else preferred


@_runtime
def append_capacity(capacity: int, item_size: int) -> int:
    if capacity >= 9223372036854775807:
        return -1
    return growth_capacity(capacity, capacity + 1, item_size, 4)


@_runtime
def clear_tail(data: Pointer, length: int, following: int, item_size: int) -> None:
    # The GC traces spare capacity too: shrinking must erase stale references.
    fill(byte_offset(data, following * item_size), int8(0), (length - following) * item_size)


@_runtime
def truncate(value: Pointer, following: int, item_size: int) -> None:
    clear_tail(load_pointer(byte_offset(value, ITEMS_OFFSET)), load_integer(value), following, item_size)
    store_integer(value, following)


@_runtime
def remove_index(value: Pointer, index: int, item_size: int) -> bool:
    length = load_integer(value)
    actual = index + length if index < 0 else index
    if actual < 0 or actual >= length:
        return False
    data = load_pointer(byte_offset(value, ITEMS_OFFSET))
    move(byte_offset(data, actual * item_size), byte_offset(data, (actual + 1) * item_size),
         (length - actual - 1) * item_size)
    truncate(value, length - 1, item_size)
    return True


@_runtime
def remove_slice(value: Pointer, item_size: int, start: int, start_present: bool,
                 stop: int, stop_present: bool, step: int, step_present: bool) -> bool:
    stride = step if step_present else 1
    if stride == 0:
        return False
    length = load_integer(value)
    reverse = stride < 0
    first = slice_bound(length, start, reverse) if start_present else length - 1 if reverse else 0
    limit = slice_bound(length, stop, reverse) if stop_present else -1 if reverse else length
    data = load_pointer(byte_offset(value, ITEMS_OFFSET))
    if stride == 1:
        if limit > first:
            move(byte_offset(data, first * item_size), byte_offset(data, limit * item_size),
                 (length - limit) * item_size)
            truncate(value, length - (limit - first), item_size)
        return True
    read = 0
    written = 0
    while read < length:
        selected = False
        if reverse:
            if read <= first and read > limit:
                # abs(INT64_MIN) cannot fit, but a list index distance can
                # never reach that stride: only the first index is selected.
                if stride == -9223372036854775808:
                    selected = read == first
                else:
                    distance = first - read
                    selected = distance == _positive_quotient(distance, -stride) * -stride
        elif read >= first and read < limit:
            distance = read - first
            selected = distance == _positive_quotient(distance, stride) * stride
        if not selected:
            if written != read:
                move(byte_offset(data, written * item_size), byte_offset(data, read * item_size), item_size)
            written += 1
        read += 1
    truncate(value, written, item_size)
    return True


@_runtime
def require_success(success: bool) -> None:
    if not success:
        trap()


@_runtime
def repeat_list(arena: Pointer, allocator: Pointer, context: Pointer, source: Pointer,
                item_size: int, count: int, inplace: bool) -> Pointer:
    length = load_integer(source)
    count = count if count > 0 else 0
    if length > 0 and count > _positive_quotient(9223372036854775807, length):
        return null()
    result = source if inplace else new_list(arena, allocator, context, item_size, 0)
    if is_null(result):
        return null()
    if not repeat(arena, result, source, item_size, length * count):
        return null()
    return result


@_runtime
def concat(arena: Pointer, allocator: Pointer, context: Pointer, left: Pointer,
           right: Pointer, item_size: int, immutable: bool) -> Pointer:
    left_length = load_integer(left)
    right_length = load_integer(right)
    if immutable and left_length == 0:
        return right
    if immutable and right_length == 0:
        return left
    if left_length < 0 or right_length < 0 or item_size <= 0:
        return null()
    maximum = _positive_quotient(9223372036854775807 - TUPLE_DATA, item_size)
    if left_length > maximum or right_length > maximum - left_length:
        return null()
    length = left_length + right_length
    # Allocate the final payload once. Copy-then-extend retains an intermediate
    # buffer in an arena and can fail even when both inputs and the result fit.
    result = (new_tuple(arena, allocator, context, length * item_size, length) if immutable
              else new_list(arena, allocator, context, item_size, length))
    if is_null(result):
        return null()
    data = load_pointer(byte_offset(result, ITEMS_OFFSET))
    copy(data, load_pointer(byte_offset(left, ITEMS_OFFSET)), left_length * item_size)
    copy(byte_offset(data, left_length * item_size), load_pointer(byte_offset(right, ITEMS_OFFSET)),
         right_length * item_size)
    return result


@_runtime
def concat_tuple(arena: Pointer, allocator: Pointer, context: Pointer, left: Pointer,
                 right: Pointer, item_size: int) -> Pointer:
    return concat(arena, allocator, context, left, right, item_size, True)


@_runtime
def concat_list(arena: Pointer, allocator: Pointer, context: Pointer, left: Pointer,
                right: Pointer, item_size: int) -> Pointer:
    return concat(arena, allocator, context, left, right, item_size, False)


@_runtime
def repeat_tuple(arena: Pointer, allocator: Pointer, context: Pointer, source: Pointer,
                 item_size: int, count: int) -> Pointer:
    if count == 1 or load_integer(source) == 0:
        return source
    return repeat_list(arena, allocator, context, source, item_size, count, False)


@_runtime
def search(value: Pointer, item: Pointer, item_size: int, kind: int8,
           start: int, stop: int, counting: bool) -> int:
    length = load_integer(value)
    first = slice_bound(length, start, False)
    limit = slice_bound(length, stop, False)
    data = load_pointer(byte_offset(value, ITEMS_OFFSET))
    count = 0
    while first < limit:
        if key_equal(byte_offset(data, first * item_size), item, kind):
            if not counting:
                return first
            count += 1
        first += 1
    return count if counting else -1


@cache
def compiled_runtime(include_search: bool = False) -> tuple[str, ...]:
    from .compiler import compile_runtime

    roots = {
        "pyjs.tuple.trace": trace_tuple,
        "pyjs.tuple.new": new_tuple,
        "pyjs.tuple.slice": slice_tuple,
        "pyjs.tuple.repeat": repeat_tuple,
        "pyjs.tuple.concat": concat_tuple,
        "pyjs.list.new.owned": new_list,
        "pyjs.list.try.new.owned": try_new_list,
        "pyjs.list.get": get,
        "pyjs.list.append.slot": append_required,
        "pyjs.list.try.append.slot": append_slot,
        "pyjs.list.try.reserve": reserve,
        "pyjs.list.try.reserve.extension": reserve_extension,
        "pyjs.list.try.extend": extend,
        "pyjs.list.concat": concat_list,
        "pyjs.list.try.repeat": repeat,
        "pyjs.list.repeat": repeat_list,
        "pyjs.list.slice": slice_copy,
        "pyjs.list.slice.length": slice_length,
        "pyjs.list.try.assign.slice": assign_slice,
        "pyjs.list.try.insert": insert,
        "pyjs.list.truncate": truncate,
        "pyjs.list.remove": remove_index,
        "pyjs.list.remove.slice": remove_slice,
        "pyjs.list.reverse": reverse,
        "pyjs.collection.require": require,
        "pyjs.collection.require.success": require_success,
    }
    dependencies = {"pyjs.collection.try.alloc": allocate_collection}
    if include_search:
        from .algorithms import bytes_equal

        roots["pyjs.list.search"] = search
        dependencies["pyjs.string.equal"] = bytes_equal
    return compile_runtime(roots, dependencies=dependencies)
