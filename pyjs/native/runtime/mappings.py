"""Dense ordered mappings with optional insertion positions and cached hashes.

The six-field storage prefix is unchanged. Repr allocates the trailing ordinal
vector only when needed, so callback deletion can compact physical arrays
without moving the logical traversal cursor backwards. Callback-key mappings
also retain hashes so copies and lookups do not rerun stored-key callbacks.
"""

import ctypes
from functools import cache

from pyjs import int8
from pyjs.decorators import native_operation

from .algorithms import _positive_quotient, _runtime, bytes_equal
from .arena import allocate_collection, scalar_allocator
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    fill,
    invoke_checked,
    is_null,
    load_bool,
    load_integer,
    load_pointer,
    move,
    null,
    same_address,
    stack_buffer,
    store_integer,
    store_pointer,
    trap,
)
from .roots import _Frame, push_frame, try_pop_frame
from .sequences import clear_tail, growth_capacity
from .values import key_equal


class _Dict(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int64), ("capacity", ctypes.c_int64),
                ("keys", ctypes.c_void_p), ("values", ctypes.c_void_p),
                ("allocator", ctypes.c_void_p), ("context", ctypes.c_void_p),
                ("order", ctypes.c_void_p), ("next_order", ctypes.c_int64),
                ("hashes", ctypes.c_void_p), ("value_allocator", ctypes.c_void_p)]


SIZE = ctypes.sizeof(_Dict)
CAPACITY = _Dict.capacity.offset
KEYS = _Dict.keys.offset
VALUES = _Dict.values.offset
ALLOCATOR = _Dict.allocator.offset
CONTEXT = _Dict.context.offset
ORDER = _Dict.order.offset
NEXT_ORDER = _Dict.next_order.offset
HASHES = _Dict.hashes.offset
VALUE_ALLOCATOR = _Dict.value_allocator.offset
FRAME_SIZE = ctypes.sizeof(_Frame)


@native_operation("memory.mapping.header")
def allocate_header(arena: Pointer, allocator: Pointer, context: Pointer, size: int) -> Pointer:
    return allocate_collection(arena, allocator, context, size)


@_runtime
def allocate_scalar(arena: Pointer, value: Pointer, size: int) -> Pointer:
    return allocate_collection(arena, scalar_allocator(load_pointer(byte_offset(value, ALLOCATOR))),
                               load_pointer(byte_offset(value, CONTEXT)), size)


@_runtime
def reserve(arena: Pointer, value: Pointer, required: int, key_size: int, value_size: int) -> bool:
    capacity = load_integer(byte_offset(value, CAPACITY))
    width = key_size if key_size > value_size else value_size
    order = load_pointer(byte_offset(value, ORDER))
    hashes = load_pointer(byte_offset(value, HASHES))
    if (not is_null(order) or not is_null(hashes)) and width < 8:
        width = 8
    following = growth_capacity(capacity, required, width, 4)
    if key_size <= 0 or value_size <= 0 or following < 0:
        return False
    if required <= capacity:
        return True
    allocator = load_pointer(byte_offset(value, ALLOCATOR))
    context = load_pointer(byte_offset(value, CONTEXT))
    keys = allocate_collection(arena, allocator, context, following * key_size)
    if is_null(keys):
        return False
    values = allocate_collection(arena, load_pointer(byte_offset(value, VALUE_ALLOCATOR)), context, following * value_size)
    if is_null(values):
        return False
    length = load_integer(value)
    following_order = null()
    following_hashes = null()
    if not is_null(order):
        following_order = allocate_scalar(arena, value, following * 8)
        if is_null(following_order):
            return False
        copy(following_order, order, length * 8)
    if not is_null(hashes):
        following_hashes = allocate_scalar(arena, value, following * 8)
        if is_null(following_hashes):
            return False
        copy(following_hashes, hashes, length * 8)
    if length:
        copy(keys, load_pointer(byte_offset(value, KEYS)), length * key_size)
        copy(values, load_pointer(byte_offset(value, VALUES)), length * value_size)
    # Only publish once all allocations succeed. No callback or GC safe point
    # may run inside the allocator; old buffers remain valid until publication.
    store_pointer(byte_offset(value, KEYS), keys)
    store_pointer(byte_offset(value, VALUES), values)
    store_integer(byte_offset(value, CAPACITY), following)
    store_pointer(byte_offset(value, ORDER), following_order)
    store_pointer(byte_offset(value, HASHES), following_hashes)
    return True


@_runtime
def track_order(arena: Pointer, value: Pointer) -> bool:
    if not is_null(load_pointer(byte_offset(value, ORDER))):
        return True
    capacity = load_integer(byte_offset(value, CAPACITY))
    if capacity < 0 or capacity > 1152921504606846975:
        return False
    order = allocate_scalar(arena, value, capacity * 8)
    if is_null(order):
        return False
    length = load_integer(value)
    index = 0
    while index < length:
        store_integer(byte_offset(order, index * 8), index)
        index += 1
    store_integer(byte_offset(value, NEXT_ORDER), length)
    store_pointer(byte_offset(value, ORDER), order)
    return True


@_runtime
def repr_index(value: Pointer, cursor: int) -> int:
    # Positions remain sorted. Formatting, equality and callback-key scans use
    # this ordinal cursor: deleting any number of earlier dense slots cannot
    # skip a survivor or reprocess an entry. Binary search keeps scans bounded.
    order = load_pointer(byte_offset(value, ORDER))
    low = 0
    high = load_integer(value)
    while low < high:
        middle = low + _positive_quotient(high - low, 2)
        if load_integer(byte_offset(order, middle * 8)) < cursor:
            low = middle + 1
        else:
            high = middle
    return low


@_runtime
def popitem_order(value: Pointer) -> None:
    order = load_pointer(byte_offset(value, ORDER))
    length = load_integer(value)
    if not is_null(order) and length > 0:
        # CPython popitem rewinds its insertion table, unlike ordinary del.
        store_integer(byte_offset(value, NEXT_ORDER), load_integer(byte_offset(order, (length - 1) * 8)))


@_runtime
def new_mapping(arena: Pointer, allocator: Pointer, context: Pointer,
                key_size: int, value_size: int) -> Pointer:
    return new_typed_mapping(arena, allocator, allocator, context, key_size, value_size)


@_runtime
def new_typed_mapping(arena: Pointer, key_allocator: Pointer, value_allocator: Pointer, context: Pointer,
                      key_size: int, value_size: int) -> Pointer:
    if (key_size <= 0 or value_size <= 0
            or growth_capacity(0, 4, key_size, 4) < 0
            or growth_capacity(0, 4, value_size, 4) < 0):
        return null()
    result = allocate_header(arena, key_allocator, context, SIZE)
    if is_null(result):
        return null()
    fill(result, int8(0), SIZE)
    store_pointer(byte_offset(result, ALLOCATOR), key_allocator)
    store_pointer(byte_offset(result, VALUE_ALLOCATOR), value_allocator)
    store_pointer(byte_offset(result, CONTEXT), context)
    if not reserve(arena, result, 4, key_size, value_size):
        return null()
    return result


@_runtime
def find(value: Pointer, key: Pointer, key_size: int, kind: int8) -> int:
    length = load_integer(value)
    keys = load_pointer(byte_offset(value, KEYS))
    index = 0
    if kind == 2 and key_size == 8:
        # Integer equality cannot call application code. Hoist the query and
        # kind dispatch out of the dense scan; retain first-match ordering.
        # Do not read the query for an empty mapping.
        if length == 0:
            return -1
        integer = load_integer(key)
        while index < length:
            if load_integer(byte_offset(keys, index * 8)) == integer:
                return index
            index += 1
        return -1
    while index < length:
        if key_equal(byte_offset(keys, index * key_size), key, kind):
            return index
        index += 1
    return -1


@_runtime
def find_hashed(arena: Pointer, heap: Pointer, exception: Pointer,
                value: Pointer, key: Pointer, key_hash: int, compare: Pointer, key_size: int) -> int:
    # Callback keys are references or tagged unions. The emitter roots the
    # mapping/query; the typed adapter roots both loaded payloads before
    # calling application code. No backing-array pointer may be
    # dereferenced after that callback until its current identity is checked.
    captured = stack_buffer(key_size)
    index = 0
    while index < load_integer(value):
        hashes = load_pointer(byte_offset(value, HASHES))
        if load_integer(byte_offset(hashes, index * 8)) != key_hash:
            index += 1
            continue
        keys = load_pointer(byte_offset(value, KEYS))
        slot = byte_offset(keys, index * key_size)
        copy(captured, slot, key_size)
        if key_size == 8 and same_address(load_pointer(slot), load_pointer(key)):
            return index
        matched = invoke_checked(compare, arena, heap, exception, slot, key)
        if not is_null(exception) and load_bool(exception):
            return -2
        current = load_pointer(byte_offset(value, KEYS))
        if (not same_address(keys, current) or index >= load_integer(value)
                or not same_key_bits(captured, byte_offset(current, index * key_size), key_size)):
            index = 0
            continue
        if matched != 0:
            return index
        index += 1
    return -1


@_runtime
def same_key_bits(left: Pointer, right: Pointer, size: int) -> bool:
    # Callback keys use aligned pointer or tagged-payload words. This checks
    # storage stability after a callback, not Python equality (NaN included).
    offset = 0
    while offset < size:
        if load_integer(byte_offset(left, offset)) != load_integer(byte_offset(right, offset)):
            return False
        offset += 8
    return True


@_runtime
def lookup(value: Pointer, key: Pointer, key_size: int, value_size: int, kind: int8) -> Pointer:
    index = find(value, key, key_size, kind)
    if index < 0:
        return null()
    return byte_offset(load_pointer(byte_offset(value, VALUES)), index * value_size)


@_runtime
def set_slot(arena: Pointer, value: Pointer, key: Pointer, key_size: int,
             value_size: int, kind: int8) -> Pointer:
    existing = lookup(value, key, key_size, value_size, kind)
    if not is_null(existing):
        return existing
    return append_entry(arena, value, key, key_size, value_size)


@_runtime
def append_entry(arena: Pointer, value: Pointer, key: Pointer, key_size: int,
                 value_size: int) -> Pointer:
    # The caller has already established absence. Custom key lookups must not
    # repeat hash/equality callbacks just to reserve their insertion slot.
    length = load_integer(value)
    ordinal = load_integer(byte_offset(value, NEXT_ORDER))
    if not is_null(load_pointer(byte_offset(value, ORDER))) and ordinal == 9223372036854775807:
        return null()
    if length == 9223372036854775807 or not reserve(arena, value, length + 1, key_size, value_size):
        return null()
    order = load_pointer(byte_offset(value, ORDER))
    if not is_null(order):
        store_integer(byte_offset(order, length * 8), ordinal)
        store_integer(byte_offset(value, NEXT_ORDER), ordinal + 1)
    copy(byte_offset(load_pointer(byte_offset(value, KEYS)), length * key_size), key, key_size)
    slot = byte_offset(load_pointer(byte_offset(value, VALUES)), length * value_size)
    # Caller stores the value before any application code or GC safe point.
    store_integer(value, length + 1)
    return slot


@_runtime
def append_hashed(arena: Pointer, value: Pointer, key: Pointer, key_size: int,
                  value_size: int, key_hash: int) -> Pointer:
    hashes = load_pointer(byte_offset(value, HASHES))
    if is_null(hashes):
        # A nonempty custom mapping always owns a hash for every key. It is not
        # valid to retrofit a cache onto arbitrary nonempty primitive storage.
        if load_integer(value) != 0:
            trap()
        capacity = load_integer(byte_offset(value, CAPACITY))
        if capacity < 0 or capacity > 1152921504606846975:
            return null()
        hashes = allocate_scalar(arena, value, capacity * 8)
        if is_null(hashes):
            return null()
        store_pointer(byte_offset(value, HASHES), hashes)
    slot = append_entry(arena, value, key, key_size, value_size)
    if not is_null(slot):
        hashes = load_pointer(byte_offset(value, HASHES))
        store_integer(byte_offset(hashes, (load_integer(value) - 1) * 8), key_hash)
    return slot


@_runtime
def remove_index(value: Pointer, index: int, key_size: int, value_size: int) -> None:
    length = load_integer(value)
    if index < 0 or index >= length:
        trap()
    keys = load_pointer(byte_offset(value, KEYS))
    values = load_pointer(byte_offset(value, VALUES))
    order = load_pointer(byte_offset(value, ORDER))
    hashes = load_pointer(byte_offset(value, HASHES))
    if not is_null(hashes):
        move(byte_offset(hashes, index * 8), byte_offset(hashes, (index + 1) * 8), (length - index - 1) * 8)
        clear_tail(hashes, length, length - 1, 8)
    if not is_null(order):
        move(byte_offset(order, index * 8), byte_offset(order, (index + 1) * 8), (length - index - 1) * 8)
    move(byte_offset(keys, index * key_size), byte_offset(keys, (index + 1) * key_size),
         (length - index - 1) * key_size)
    move(byte_offset(values, index * value_size), byte_offset(values, (index + 1) * value_size),
         (length - index - 1) * value_size)
    clear_tail(keys, length, length - 1, key_size)
    clear_tail(values, length, length - 1, value_size)
    store_integer(value, length - 1)


@_runtime
def clear(value: Pointer, key_size: int, value_size: int) -> None:
    length = load_integer(value)
    clear_tail(load_pointer(byte_offset(value, KEYS)), length, 0, key_size)
    clear_tail(load_pointer(byte_offset(value, VALUES)), length, 0, value_size)
    hashes = load_pointer(byte_offset(value, HASHES))
    if not is_null(hashes):
        clear_tail(hashes, length, 0, 8)
    store_integer(value, 0)
    store_integer(byte_offset(value, NEXT_ORDER), 0)


@_runtime
def update(arena: Pointer, target: Pointer, source: Pointer, key_size: int,
           value_size: int, kind: int8) -> bool:
    if same_address(target, source):
        return True
    length = load_integer(source)
    keys = load_pointer(byte_offset(source, KEYS))
    values = load_pointer(byte_offset(source, VALUES))
    index = 0
    while index < length:
        slot = set_slot(arena, target, byte_offset(keys, index * key_size), key_size, value_size, kind)
        if is_null(slot):
            return False
        copy(slot, byte_offset(values, index * value_size), value_size)
        index += 1
    return True


@_runtime
def update_hashed(arena: Pointer, heap: Pointer, exception: Pointer, target: Pointer,
                  source: Pointer, value_size: int, compare: Pointer, key_size: int) -> int:
    """Merge cached hashes: 1 success, 0 OOM, -1 mutation, -2 callback error."""
    return update_known_hashes(arena, heap, exception, target, source, value_size, compare, key_size, null(), True)


@_runtime
def update_keys(arena: Pointer, heap: Pointer, exception: Pointer, target: Pointer,
                source: Pointer, value_size: int, compare: Pointer, key_size: int,
                default: Pointer, copy_empty: bool) -> int:
    return update_known_hashes(arena, heap, exception, target, source, value_size, compare, key_size, default, copy_empty)


@_runtime
def update_known_hashes(arena: Pointer, heap: Pointer, exception: Pointer, target: Pointer,
                        source: Pointer, value_size: int, compare: Pointer, key_size: int,
                        default: Pointer, copy_empty: bool) -> int:
    if same_address(target, source) or load_integer(source) == 0:
        return 1
    if load_integer(target) == 0 and copy_empty:
        if not is_null(default):
            return 1 if copy_keys(arena, target, source, key_size, value_size, default) else 0
        return 1 if replace(arena, target, source, key_size, value_size) else 0
    # Equality may clear either mapping, so retaining their headers alone is
    # insufficient. Snapshot/root the current key and value independently.
    # Conservative roots are aligned machine words, including padded scalar
    # storage; never read an eight-byte root from a one-byte bool buffer.
    item_offset = 16 + key_size
    words = _positive_quotient(item_offset + value_size + 7, 8)
    saved = stack_buffer(words * 8)
    slots = stack_buffer(words * 8)
    frame = stack_buffer(FRAME_SIZE)
    fill(saved, int8(0), words * 8)
    store_pointer(saved, target)
    store_pointer(byte_offset(saved, 8), source)
    if not is_null(default):
        copy(byte_offset(saved, item_offset), default, value_size)
    index = 0
    while index < words:
        store_pointer(byte_offset(slots, index * 8), byte_offset(saved, index * 8))
        index += 1
    if not is_null(heap):
        push_frame(heap, frame, slots, words)
    result = merge_hashed(arena, heap, exception, target, source, value_size, compare, key_size,
                          byte_offset(saved, 16), byte_offset(saved, item_offset), is_null(default))
    if not is_null(heap) and not try_pop_frame(heap, frame):
        trap()
    return result


@_runtime
def merge_hashed(arena: Pointer, heap: Pointer, exception: Pointer, target: Pointer,
                 source: Pointer, value_size: int, compare: Pointer, key_size: int,
                 key: Pointer, item: Pointer, source_values: bool) -> int:
    length = load_integer(source)
    cursor = 0
    if not track_order(arena, source):
        return 0
    while True:
        # Dict updates can delete and insert within one callback without changing
        # length. They need the same stable cursor as sets, in addition to their
        # post-publication size check below.
        index = repr_index(source, cursor)
        if index >= load_integer(source):
            break
        cursor = load_integer(byte_offset(load_pointer(byte_offset(source, ORDER)), index * 8)) + 1
        copy(key, byte_offset(load_pointer(byte_offset(source, KEYS)), index * key_size), key_size)
        if source_values:
            copy(item, byte_offset(load_pointer(byte_offset(source, VALUES)), index * value_size), value_size)
        hashed = load_integer(byte_offset(load_pointer(byte_offset(source, HASHES)), index * 8))
        found = find_hashed(arena, heap, exception, target, key, hashed, compare, key_size)
        if found == -2:
            return -2
        if found < 0:
            slot = append_hashed(arena, target, key, key_size, value_size, hashed)
            if is_null(slot):
                return 0
        else:
            slot = byte_offset(load_pointer(byte_offset(target, VALUES)), found * value_size)
        copy(slot, item, value_size)
        # Dict update publishes this entry before detecting source-size changes.
        # Set update instead follows the current source, even after shrinkage.
        # In either case callbacks invalidate cached array addresses.
        if source_values and load_integer(source) != length:
            return -1
    return 1


@_runtime
def copy_mapping(arena: Pointer, allocator: Pointer, context: Pointer, source: Pointer,
                 key_size: int, value_size: int, kind: int8) -> Pointer:
    return copy_typed_mapping(arena, allocator, allocator, context, source, key_size, value_size, kind)


@_runtime
def copy_typed_mapping(arena: Pointer, key_allocator: Pointer, value_allocator: Pointer, context: Pointer,
                       source: Pointer, key_size: int, value_size: int, kind: int8) -> Pointer:
    result = new_typed_mapping(arena, key_allocator, value_allocator, context, key_size, value_size)
    if is_null(result) or not replace(arena, result, source, key_size, value_size):
        return null()
    return result


@_runtime
def copy_keys(arena: Pointer, target: Pointer, source: Pointer, key_size: int,
              value_size: int, default: Pointer) -> bool:
    """Populate fresh fromkeys storage without rehashing a mapping/set source."""
    if load_integer(target) != 0:
        trap()
    length = load_integer(source)
    if not reserve(arena, target, length, key_size, value_size):
        return False
    hashes = load_pointer(byte_offset(source, HASHES))
    if not is_null(hashes):
        capacity = load_integer(byte_offset(target, CAPACITY))
        if capacity > 1152921504606846975:
            return False
        cloned = allocate_scalar(arena, target, capacity * 8)
        if is_null(cloned):
            return False
        copy(cloned, hashes, length * 8)
        store_pointer(byte_offset(target, HASHES), cloned)
    copy(load_pointer(byte_offset(target, KEYS)), load_pointer(byte_offset(source, KEYS)), length * key_size)
    values = load_pointer(byte_offset(target, VALUES))
    index = 0
    while index < length:
        copy(byte_offset(values, index * value_size), default, value_size)
        index += 1
    store_integer(target, length)
    return True


@_runtime
def replace(arena: Pointer, target: Pointer, source: Pointer, key_size: int, value_size: int) -> bool:
    if same_address(target, source):
        return True
    length = load_integer(source)
    hashes = load_pointer(byte_offset(source, HASHES))
    cloned_hashes = null()
    if not is_null(hashes) and is_null(load_pointer(byte_offset(target, HASHES))):
        capacity = growth_capacity(load_integer(byte_offset(target, CAPACITY)), length,
                                    max(key_size, value_size, 8), 4)
        if capacity < 0:
            return False
        cloned_hashes = allocate_scalar(arena, target, capacity * 8)
        if is_null(cloned_hashes):
            return False
    if not reserve(arena, target, length, key_size, value_size):
        return False
    # Preserve the target's allocator. Swapping headers could leave an arena
    # object owning untraced heap buffers. Reserve before changing contents.
    previous = load_integer(target)
    if not is_null(cloned_hashes):
        store_pointer(byte_offset(target, HASHES), cloned_hashes)
    target_hashes = load_pointer(byte_offset(target, HASHES))
    if not is_null(hashes):
        copy(target_hashes, hashes, length * 8)
        if previous > length:
            clear_tail(target_hashes, previous, length, 8)
    else:
        store_pointer(byte_offset(target, HASHES), null())
    keys = load_pointer(byte_offset(target, KEYS))
    values = load_pointer(byte_offset(target, VALUES))
    copy(keys, load_pointer(byte_offset(source, KEYS)), length * key_size)
    copy(values, load_pointer(byte_offset(source, VALUES)), length * value_size)
    if previous > length:
        clear_tail(keys, previous, length, key_size)
        clear_tail(values, previous, length, value_size)
    store_integer(target, length)
    order = load_pointer(byte_offset(target, ORDER))
    if not is_null(order):
        index = 0
        while index < length:
            store_integer(byte_offset(order, index * 8), index)
            index += 1
        store_integer(byte_offset(target, NEXT_ORDER), length)
    return True


@cache
def compiled_runtime() -> tuple[str, ...]:
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.dict.new.owned": new_mapping,
        "pyjs.dict.new.typed": new_typed_mapping,
        "pyjs.dict.key.equal": key_equal,
        "pyjs.dict.find": find,
        "pyjs.dict.find.hashed": find_hashed,
        "pyjs.dict.lookup": lookup,
        "pyjs.dict.set.slot": set_slot,
        "pyjs.dict.append.hashed": append_hashed,
        "pyjs.dict.remove.index": remove_index,
        "pyjs.dict.clear": clear,
        "pyjs.dict.update": update,
        "pyjs.dict.update.hashed": update_hashed,
        "pyjs.dict.update.keys": update_keys,
        "pyjs.dict.copy": copy_mapping,
        "pyjs.dict.copy.typed": copy_typed_mapping,
        "pyjs.dict.copy.keys": copy_keys,
        "pyjs.dict.replace": replace,
        "pyjs.dict.try.reserve": reserve,
        "pyjs.dict.track.order": track_order,
        "pyjs.dict.repr.index": repr_index,
        "pyjs.dict.popitem.order": popitem_order,
        "pyjs.dict.pop.into": pop_into,
        "pyjs.set.subset": subset,
        "pyjs.set.subset.distinct": subset_distinct,
        "pyjs.set.relation.hashed": relation_hashed,
        "pyjs.set.intersection.hashed": intersection_hashed,
        "pyjs.set.select.hashed": select_hashed,
        "pyjs.set.discard.hashed": discard_hashed,
        "pyjs.set.toggle.hashed": toggle_hashed,
        "pyjs.set.intersect": intersect,
        "pyjs.set.symmetric.difference": symmetric_difference,
    }, dependencies={"pyjs.collection.try.alloc": allocate_collection,
                     "pyjs.string.equal": bytes_equal})


@_runtime
def pop_into(value: Pointer, key: Pointer, key_size: int, value_size: int,
             kind: int8, output: Pointer) -> bool:
    index = find(value, key, key_size, kind)
    if index < 0:
        return False
    if not is_null(output):
        copy(output, byte_offset(load_pointer(byte_offset(value, VALUES)), index * value_size), value_size)
    remove_index(value, index, key_size, value_size)
    return True


@_runtime
def subset(left: Pointer, right: Pointer, size: int, kind: int8, disjoint: bool) -> bool:
    length = load_integer(left)
    keys = load_pointer(byte_offset(left, KEYS))
    index = 0
    while index < length:
        present = find(right, byte_offset(keys, index * size), size, kind) >= 0
        if present == disjoint:
            return False
        index += 1
    return True


@_runtime
def subset_distinct(arena: Pointer, heap: Pointer, exception: Pointer,
                    left: Pointer, right: Pointer, left_size: int, right_size: int,
                    compare: Pointer, disjoint: bool) -> bool:
    """Read-only primitive relation; each side retains its own item layout.

    The adapter admits only builtins with no user equality callbacks, so keys
    and lengths remain stable throughout the scan. Like subset(), this uses
    the dense mapping runtime's linear lookup rather than building a temporary.
    """
    left_keys = load_pointer(byte_offset(left, KEYS))
    right_keys = load_pointer(byte_offset(right, KEYS))
    index = 0
    while index < load_integer(left):
        other = 0
        present = False
        while other < load_integer(right):
            if invoke_checked(compare, arena, heap, exception,
                              byte_offset(left_keys, index * left_size),
                              byte_offset(right_keys, other * right_size)) != 0:
                present = True
                break
            other += 1
        if present == disjoint:
            return False
        index += 1
    return True


@_runtime
def relation_hashed(arena: Pointer, heap: Pointer, exception: Pointer,
                    left: Pointer, right: Pointer, compare: Pointer, relation: int8, key_size: int) -> int:
    """Return 0/1, -2 callback failure, -3 OOM; relations: subset/proper/equal/disjoint."""
    own_length = load_integer(left)
    other_length = load_integer(right)
    if relation == 3:
        if same_address(left, right):
            return 1 if own_length == 0 else 0
        # Probe the larger set; on equal sizes Python iterates the argument.
        if own_length >= other_length:
            # Tuple assignment would allocate in the runtime-helper subset.
            previous = left
            left = right
            right = previous
    elif (own_length > other_length or relation == 1 and own_length == other_length
          or relation == 2 and own_length != other_length):
        # Size rejection precedes application equality, which can raise/mutate.
        return 0
    size = 16 + key_size
    words = _positive_quotient(size, 8)
    saved = stack_buffer(size)
    slots = stack_buffer(size)
    frame = stack_buffer(FRAME_SIZE)
    store_pointer(saved, left)
    store_pointer(byte_offset(saved, 8), right)
    fill(byte_offset(saved, 16), int8(0), key_size)
    index = 0
    while index < words:
        store_pointer(byte_offset(slots, index * 8), byte_offset(saved, index * 8))
        index += 1
    if not is_null(heap):
        push_frame(heap, frame, slots, words)
    result = scan_relation(arena, heap, exception, left, right, compare, key_size,
                           byte_offset(saved, 16), relation == 3)
    if not is_null(heap) and not try_pop_frame(heap, frame):
        trap()
    return result


@_runtime
def scan_relation(arena: Pointer, heap: Pointer, exception: Pointer,
                   left: Pointer, right: Pointer, compare: Pointer, key_size: int, key: Pointer,
                   disjoint: bool) -> int:
    if not track_order(arena, left):
        return -3
    cursor = 0
    while True:
        index = repr_index(left, cursor)
        if index >= load_integer(left):
            break
        cursor = load_integer(byte_offset(load_pointer(byte_offset(left, ORDER)), index * 8)) + 1
        # Keep the current key alive if equality clears the source and collects.
        copy(key, byte_offset(load_pointer(byte_offset(left, KEYS)), index * key_size), key_size)
        hashed = load_integer(byte_offset(load_pointer(byte_offset(left, HASHES)), index * 8))
        found = find_hashed(arena, heap, exception, right, key, hashed, compare, key_size)
        if found == -2:
            return -2
        if (found >= 0) == disjoint:
            return 0
    return 1


@_runtime
def intersection_hashed(arena: Pointer, heap: Pointer, exception: Pointer,
                        left: Pointer, right: Pointer, result: Pointer, compare: Pointer, key_size: int) -> int:
    if same_address(left, right):
        return 1 if replace(arena, result, left, key_size, 1) else 0
    # Preserve the smaller operand's key objects, using the argument on ties.
    if load_integer(left) >= load_integer(right):
        previous = left
        left = right
        right = previous
    return select_hashed(arena, heap, exception, left, right, result, compare, key_size, True)


@_runtime
def select_hashed(arena: Pointer, heap: Pointer, exception: Pointer,
                  left: Pointer, right: Pointer, result: Pointer, compare: Pointer,
                  key_size: int, matches: bool) -> int:
    """Copy matching/nonmatching left keys, retaining them across callbacks."""
    size = 24 + key_size
    words = _positive_quotient(size, 8)
    saved = stack_buffer(size)
    slots = stack_buffer(size)
    frame = stack_buffer(FRAME_SIZE)
    store_pointer(saved, left)
    store_pointer(byte_offset(saved, 8), right)
    store_pointer(byte_offset(saved, 16), result)
    fill(byte_offset(saved, 24), int8(0), key_size)
    index = 0
    while index < words:
        store_pointer(byte_offset(slots, index * 8), byte_offset(saved, index * 8))
        index += 1
    if not is_null(heap):
        push_frame(heap, frame, slots, words)
    status = collect_selected(arena, heap, exception, left, right, result, compare, key_size,
                              byte_offset(saved, 24), matches)
    if not is_null(heap) and not try_pop_frame(heap, frame):
        trap()
    return status


@_runtime
def collect_selected(arena: Pointer, heap: Pointer, exception: Pointer,
                     left: Pointer, right: Pointer, result: Pointer,
                     compare: Pointer, key_size: int, key: Pointer, matches: bool) -> int:
    if not track_order(arena, left):
        return 0
    cursor = 0
    while True:
        index = repr_index(left, cursor)
        if index >= load_integer(left):
            break
        cursor = load_integer(byte_offset(load_pointer(byte_offset(left, ORDER)), index * 8)) + 1
        copy(key, byte_offset(load_pointer(byte_offset(left, KEYS)), index * key_size), key_size)
        hashed = load_integer(byte_offset(load_pointer(byte_offset(left, HASHES)), index * 8))
        found = find_hashed(arena, heap, exception, right, key, hashed, compare, key_size)
        if found == -2:
            return -2
        if (found >= 0) == matches:
            # Mutation can make a later source item duplicate a captured one.
            present = find_hashed(arena, heap, exception, result, key, hashed, compare, key_size)
            if present == -2:
                return -2
            if present < 0:
                slot = append_hashed(arena, result, key, key_size, 1, hashed)
                if is_null(slot):
                    return 0
                fill(slot, int8(1), 1)
    return 1


@_runtime
def discard_hashed(arena: Pointer, heap: Pointer, exception: Pointer,
                   target: Pointer, source: Pointer, compare: Pointer, key_size: int) -> int:
    if same_address(target, source):
        clear(target, key_size, 1)
        return 1
    # Match CPython's size heuristic: the prefilter compares in the other
    # direction and must finish before any removal is published.
    if _positive_quotient(load_integer(source), 8) > load_integer(target):
        filtered = new_typed_mapping(arena, load_pointer(byte_offset(target, ALLOCATOR)),
                                      load_pointer(byte_offset(target, VALUE_ALLOCATOR)),
                                      load_pointer(byte_offset(target, CONTEXT)), key_size, 1)
        if is_null(filtered):
            return 0
        status = intersection_hashed(arena, heap, exception, target, source, filtered, compare, key_size)
        if status != 1:
            return status
        source = filtered
    return mutate_hashed(arena, heap, exception, target, source, compare, key_size, False)


@_runtime
def toggle_hashed(arena: Pointer, heap: Pointer, exception: Pointer,
                  target: Pointer, source: Pointer, compare: Pointer, key_size: int) -> int:
    return mutate_hashed(arena, heap, exception, target, source, compare, key_size, True)


@_runtime
def mutate_hashed(arena: Pointer, heap: Pointer, exception: Pointer,
                  target: Pointer, source: Pointer, compare: Pointer, key_size: int, toggle: bool) -> int:
    if same_address(target, source):
        clear(target, key_size, 1)
        return 1
    size = 16 + key_size
    words = _positive_quotient(size, 8)
    saved = stack_buffer(size)
    slots = stack_buffer(size)
    frame = stack_buffer(FRAME_SIZE)
    store_pointer(saved, target)
    store_pointer(byte_offset(saved, 8), source)
    fill(byte_offset(saved, 16), int8(0), key_size)
    index = 0
    while index < words:
        store_pointer(byte_offset(slots, index * 8), byte_offset(saved, index * 8))
        index += 1
    if not is_null(heap):
        push_frame(heap, frame, slots, words)
    status = scan_mutations(arena, heap, exception, target, source, compare, key_size,
                            byte_offset(saved, 16), toggle)
    if not is_null(heap) and not try_pop_frame(heap, frame):
        trap()
    return status


@_runtime
def scan_mutations(arena: Pointer, heap: Pointer, exception: Pointer,
                   target: Pointer, source: Pointer, compare: Pointer, key_size: int,
                   key: Pointer, toggle: bool) -> int:
    if not track_order(arena, source):
        return 0
    cursor = 0
    while True:
        index = repr_index(source, cursor)
        if index >= load_integer(source):
            break
        cursor = load_integer(byte_offset(load_pointer(byte_offset(source, ORDER)), index * 8)) + 1
        copy(key, byte_offset(load_pointer(byte_offset(source, KEYS)), index * key_size), key_size)
        hashed = load_integer(byte_offset(load_pointer(byte_offset(source, HASHES)), index * 8))
        found = find_hashed(arena, heap, exception, target, key, hashed, compare, key_size)
        if found == -2:
            return -2
        if found >= 0:
            remove_index(target, found, key_size, 1)
        elif toggle:
            # Python's failed discard is followed by a separate insertion
            # lookup. Both comparisons are observable, and either may mutate.
            found = find_hashed(arena, heap, exception, target, key, hashed, compare, key_size)
            if found == -2:
                return -2
            if found < 0:
                slot = append_hashed(arena, target, key, key_size, 1, hashed)
                if is_null(slot):
                    return 0
                fill(slot, int8(1), 1)
    return 1


@_runtime
def intersect(value: Pointer, other: Pointer, size: int, kind: int8, difference: bool) -> None:
    index = 0
    while index < load_integer(value):
        key = byte_offset(load_pointer(byte_offset(value, KEYS)), index * size)
        present = find(other, key, size, kind) >= 0
        if present == difference:
            remove_index(value, index, size, 1)
        else:
            index += 1


@_runtime
def symmetric_difference(arena: Pointer, value: Pointer, other: Pointer, size: int, kind: int8) -> bool:
    if same_address(value, other):
        clear(value, size, 1)
        return True
    length = load_integer(other)
    keys = load_pointer(byte_offset(other, KEYS))
    index = 0
    while index < length:
        key = byte_offset(keys, index * size)
        present = find(value, key, size, kind)
        if present >= 0:
            remove_index(value, present, size, 1)
        else:
            slot = set_slot(arena, value, key, size, 1, kind)
            if is_null(slot):
                return False
            fill(slot, int8(1), 1)
        index += 1
    return True
