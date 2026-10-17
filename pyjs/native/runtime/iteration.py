"""Lazy concrete iterators with checked, allocation-owned state.

Advancement returns 1 for a value, 0 for exhaustion, or a negative error code.
Callback adapters use the current advancement context, never a retained stack
pointer. In-flight rows and their states are rooted across managed callbacks.
"""

import ctypes
from functools import cache

from pyjs import int8, int64
from pyjs.decorators import native_operation

from .algorithms import _byte_at, _positive_quotient, _runtime, character_width
from .arena import allocate_collection
from .combinatorics import (
    COMBINATIONS,
    PERMUTATIONS,
    PRODUCT,
    REPLACEMENT,
    combinations_advance,
    permutations_advance,
    product_advance,
)
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    copy,
    fill,
    invoke_checked,
    is_null,
    load_float,
    load_integer,
    load_pointer,
    null,
    same_address,
    stack_buffer,
    store_float,
    store_integer,
    store_pointer,
    trap,
)
from .ranges import last, length_wide
from .roots import _Frame, push_frame, try_pop_frame
from .sequences import ITEMS_OFFSET, append_slot, new_tuple
from .text_edit import copy_span
from .traces import EXCEPTION_SIZE
from .wide import narrow

LIST = 1
TUPLE = 2
KEYS = 3
VALUES = 4
ITEMS = 5
RANGE = 6
TEXT = 7
BYTES = 8
ENUMERATE = 9
ZIP = 10
REVERSE_RANGE = 11
SET_KEYS = 12
CALLBACK = 13
GENERATOR = 14
REPEAT = 15
ISLICE = 16
PAIRWISE = 17
BATCHED = 18
POOLED = 19
COUNT_INT = 20
COUNT_FLOAT = 21
CYCLE = 22
ZIP_LONGEST = 23
TEE = 24
GROUPBY = 25
GROUPER = 26
APPLICATION = 27
ADAPTER = 28
COUNT_MIXED = 29
CALLBACK_ERROR = -9223372036854775808
INCOMPLETE_BATCH = -9223372036854775807
TEE_REENTRY = -9223372036854775806
CALLBACK_STOP = -9223372036854775805

# Forward-only blocks let GC release consumed history without a registry of
# cursors, weak references, or a buffer retained for the entire stream.
TEE_CAPACITY = 32
TEE_SOURCE = 0
TEE_NEXT = 8
TEE_COUNT = 16
TEE_RUNNING = 24
TEE_DATA = 32

# The group workspace starts with a padded slot stride and active cursor,
# plus the key allocator and layout, followed by pending value, pending key
# and target key. Neither values nor keys are necessarily one word (closed
# unions carry a tag and payload).
GROUP_ACTIVE = 8
GROUP_KEY_ALLOCATOR = 16
GROUP_LAYOUT = 24
GROUP_VALUES = 32
# Shared with the emitter: two-bit slot codes encode scalar, reference or
# tagged storage. Tagged payloads follow their one-word discriminator.
GROUP_SCALAR = 0
GROUP_REFERENCE = 1
GROUP_TAGGED = 2
GROUP_KEY_SHIFT = 2
GROUP_KEY_FACTOR = 1 << GROUP_KEY_SHIFT
GROUP_SLOT_MASK = GROUP_KEY_FACTOR - 1
GROUP_TAGGED_PAYLOAD = 8
# GROUPBY reuses INDEX/LIMIT for current/target presence, STEP for whether the
# pending item opened the current group, COUNT for key size,
# ADVANCE/OFFSETS for key/equality adapters, and STRICT for the row's cursor
# offset. GROUPER stores its owned target buffer in CALLBACK_VALUE and parent
# in SOURCE; never put variable-width key bits inside the fixed state header.
# GENERATOR uses SOURCE for its frame, CALLBACK_VALUE for the frame's typed
# input slot, STEP for input presence, INDEX for resume position and STRICT
# for reentrancy. The callback owns these fields; generic advancement must not.
# ADAPTER retains a source cursor in SOURCE, with typed next/send/iter callbacks
# in ADVANCE/CALLBACK_VALUE/OFFSETS. It owns no generator control or input state.
# POOLED optionally uses CALLBACK_VALUE for fixed product layout: LIMIT pool
# strides followed by COUNT row offsets. OFFSETS remains the mutable indices.
# COUNT_MIXED has COUNT_FLOAT's two-double source buffer. INDEX/STEP retain the
# first integral payload/tag; LIMIT records its consumption, COUNT the float tag.
# TEE keeps its history-block allocator in OFFSETS, separate from cursor/row
# allocation. Each block also retains its source and the next history block.


class _State(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_int64), ("source", ctypes.c_void_p),
        ("index", ctypes.c_int64), ("limit", ctypes.c_int64),
        ("step", ctypes.c_int64), ("item_size", ctypes.c_int64),
        ("children", ctypes.c_void_p), ("count", ctypes.c_int64),
        ("offsets", ctypes.c_void_p), ("row_size", ctypes.c_int64),
        ("arena", ctypes.c_void_p), ("allocator", ctypes.c_void_p),
        ("owner", ctypes.c_void_p), ("exhausted", ctypes.c_int64),
        ("strict", ctypes.c_int64),
        ("advance", ctypes.c_void_p), ("callback", ctypes.c_void_p),
        ("row_allocator", ctypes.c_void_p),
    ]


SIZE = ctypes.sizeof(_State)
SOURCE = _State.source.offset
INDEX = _State.index.offset
LIMIT = _State.limit.offset
STEP = _State.step.offset
ITEM_SIZE = _State.item_size.offset
CHILDREN = _State.children.offset
COUNT = _State.count.offset
OFFSETS = _State.offsets.offset
ROW_SIZE = _State.row_size.offset
ARENA = _State.arena.offset
ALLOCATOR = _State.allocator.offset
OWNER = _State.owner.offset
EXHAUSTED = _State.exhausted.offset
STRICT = _State.strict.offset
ADVANCE = _State.advance.offset
CALLBACK_VALUE = _State.callback.offset
ROW_ALLOCATOR = _State.row_allocator.offset
FRAME_SIZE = ctypes.sizeof(_Frame)
# Derive tracing from the runtime layout, just like loads/stores above. Owner
# context and arena are not managed objects; visiting their external addresses
# is harmless. Numeric counters/tags must never be treated as references.
REFERENCE_OFFSETS = tuple(getattr(_State, name).offset for name, kind in _State._fields_ if kind is ctypes.c_void_p)


@native_operation("memory.iterator.header")
def allocate_header(arena: Pointer, allocator: Pointer, owner: Pointer, size: int) -> Pointer:
    return allocate_collection(arena, allocator, owner, size)


@_runtime
def allocate_row(state: Pointer, length: int) -> Pointer:
    size = load_integer(byte_offset(state, ROW_SIZE))
    if load_integer(state) == BATCHED:
        # Even an impossible batch width is accepted by construction. Check
        # before multiplying or consuming a child, on every retry of next().
        item_size = load_integer(byte_offset(state, ITEM_SIZE))
        if item_size <= 0 or length > _positive_quotient(9223372036854775759, item_size):
            return null()
        size = length * item_size
    return new_tuple(load_pointer(byte_offset(state, ARENA)),
                     load_pointer(byte_offset(state, ROW_ALLOCATOR)),
                     load_pointer(byte_offset(state, OWNER)),
                     size, length)


@_runtime
def create(arena: Pointer, allocator: Pointer, owner: Pointer, kind: int,
           source: Pointer, index: int, limit: int, step: int, item_size: int) -> Pointer:
    state = allocate_header(arena, allocator, owner, SIZE)
    if is_null(state):
        return null()
    fill(state, int8(0), SIZE)
    store_integer(state, kind)
    store_pointer(byte_offset(state, SOURCE), source)
    store_integer(byte_offset(state, INDEX), index)
    store_integer(byte_offset(state, LIMIT), limit)
    store_integer(byte_offset(state, STEP), step)
    store_integer(byte_offset(state, ITEM_SIZE), item_size)
    store_pointer(byte_offset(state, ARENA), arena)
    store_pointer(byte_offset(state, ALLOCATOR), allocator)
    # Auxiliary storage has different layouts from emitted rows. A typed row
    # owner must not become the allocator for cursor pools or saved values.
    store_pointer(byte_offset(state, ROW_ALLOCATOR), allocator)
    store_pointer(byte_offset(state, OWNER), owner)
    if kind == REVERSE_RANGE:
        start = load_integer(source)
        stop = load_integer(byte_offset(source, 8))
        stride = load_integer(byte_offset(source, 16))
        count = narrow(length_wide(start, stop, stride))
        store_integer(byte_offset(state, LIMIT), count)
        store_integer(byte_offset(state, STEP), stride)
        if count != 0:
            store_integer(byte_offset(state, INDEX), last(start, stop, stride))
    return state


@_runtime
def finish(state: Pointer) -> int:
    store_integer(byte_offset(state, EXHAUSTED), 1)
    # Exhausted handles remain valid and retain identity, not their sources.
    store_pointer(byte_offset(state, SOURCE), null())
    store_pointer(byte_offset(state, CHILDREN), null())
    store_pointer(byte_offset(state, CALLBACK_VALUE), null())
    return 0


@_runtime
def consume_stop(status: int, context: Pointer) -> int:
    # A tagged StopIteration retains its checked-ABI exception until consumed.
    # Drop its payload root too: loops/defaulted next discard completion values.
    if status == CALLBACK_STOP:
        fill(load_pointer(byte_offset(context, 16)), int8(0), EXCEPTION_SIZE)
        return 0
    return status


@_runtime
def advance(state: Pointer, output: Pointer) -> int:
    return advance_context(state, output, null())


@_runtime
def control(state: Pointer) -> Pointer:
    # Views retain their source even after exhaustion: identity and generator
    # control belong to that source, whose own frame is released on completion.
    while not is_null(state) and load_integer(state) == ADAPTER:
        state = load_pointer(byte_offset(state, SOURCE))
    return state


@_runtime
def identity(state: Pointer) -> Pointer:
    state = control(state)
    if not is_null(state) and load_integer(state) == APPLICATION:
        return load_pointer(byte_offset(state, SOURCE))
    return state


@_runtime
def iterate(state: Pointer, context: Pointer) -> Pointer:
    kind = load_integer(state)
    if kind == ADAPTER:
        if load_integer(control(state)) != APPLICATION:
            return state
        callback = load_pointer(byte_offset(state, OFFSETS))
    elif kind == APPLICATION:
        callback = load_pointer(byte_offset(state, CALLBACK_VALUE))
    else:
        return state
    output = stack_buffer(8)
    store_pointer(output, null())
    invoke_checked(callback, load_pointer(context),
                   load_pointer(byte_offset(context, 8)), load_pointer(byte_offset(context, 16)), state, output)
    return load_pointer(output)


@_runtime
def advance_context(state: Pointer, output: Pointer, context: Pointer) -> int:
    kind = load_integer(state)
    if kind < 0:
        return kind
    if load_integer(byte_offset(state, EXHAUSTED)) != 0:
        return 0
    source = load_pointer(byte_offset(state, SOURCE))
    index = load_integer(byte_offset(state, INDEX))
    limit = load_integer(byte_offset(state, LIMIT))
    step = load_integer(byte_offset(state, STEP))
    size = load_integer(byte_offset(state, ITEM_SIZE))
    if kind == CALLBACK or kind == GENERATOR or kind == APPLICATION or kind == ADAPTER:
        if is_null(context):
            return CALLBACK_ERROR
        return invoke_checked(load_pointer(byte_offset(state, ADVANCE)),
                                load_pointer(context), load_pointer(byte_offset(context, 8)),
                                load_pointer(byte_offset(context, 16)), state, output)
    if kind == ENUMERATE or kind == ZIP or kind == PAIRWISE or kind == BATCHED:
        return advance_row(state, output, context)
    if kind == CYCLE or kind == ZIP_LONGEST:
        return advance_buffered(state, output, context)
    if kind == TEE:
        return advance_tee(state, output, context)
    if kind == GROUPBY or kind == GROUPER:
        return advance_group(state, output, context)
    if kind == COUNT_INT:
        store_integer(output, index)
        store_integer(byte_offset(state, INDEX), int(int64(index + step)))
        return 1
    if kind == COUNT_FLOAT or kind == COUNT_MIXED:
        value = load_float(source)
        if kind == COUNT_MIXED:
            if limit == 0:
                store_integer(output, step)
                store_integer(byte_offset(output, 8), index)
                store_integer(byte_offset(state, LIMIT), 1)
            else:
                store_integer(output, load_integer(byte_offset(state, COUNT)))
                store_float(byte_offset(output, 8), value)
        else:
            store_float(output, value)
        store_float(source, value + load_float(byte_offset(source, 8)))
        return 1
    if kind == ISLICE:
        return advance_slice(state, output, context)
    if kind == POOLED:
        return advance_pool(state, output)
    if kind == REPEAT:
        if limit == 0:
            return finish(state)
        copy(output, source, size)
        if limit > 0:
            store_integer(byte_offset(state, LIMIT), limit - 1)
        return 1
    if kind == RANGE:
        if index >= limit if step > 0 else index <= limit:
            return finish(state)
        store_integer(output, index)
        following = int(int64(index + step))
        if following < index if step > 0 else following > index:
            finish(state)
        else:
            store_integer(byte_offset(state, INDEX), following)
        return 1
    if kind == REVERSE_RANGE:
        if limit == 0:
            return finish(state)
        store_integer(output, index)
        store_integer(byte_offset(state, INDEX), int(int64(index - step)))
        store_integer(byte_offset(state, LIMIT), int(int64(limit - 1)))
        return 1
    length = limit if kind == TUPLE else load_integer(source)
    if kind == KEYS or kind == VALUES or kind == ITEMS or kind == SET_KEYS:
        if length != limit:
            error = -4 if kind == SET_KEYS else -2
            store_integer(state, error)
            return error
    if index < 0 or index >= length:
        return finish(state)
    if kind == TEXT:
        data = borrow_bytes(source)
        if step < 0:
            while index > 0 and (_byte_at(data, index) & 192) == 128:
                index -= 1
        width = character_width(data, index)
        character = copy_span(load_pointer(byte_offset(state, ARENA)),
                              load_pointer(byte_offset(state, ALLOCATOR)),
                              load_pointer(byte_offset(state, OWNER)), source, index, width)
        if is_null(character):
            return -1
        store_pointer(output, character)
        following = index + width if step > 0 else index - 1
    elif kind == BYTES:
        store_integer(output, _byte_at(borrow_bytes(source), index))
        following = index + step
    elif kind == ITEMS:
        row = allocate_row(state, 2)
        if is_null(row):
            return -1
        data = load_pointer(byte_offset(row, ITEMS_OFFSET))
        metadata = load_pointer(byte_offset(state, OFFSETS))
        key_size = load_integer(metadata)
        value_size = load_integer(byte_offset(metadata, 8))
        value_offset = load_integer(byte_offset(metadata, 16))
        copy(data, byte_offset(load_pointer(byte_offset(source, 16)), index * key_size), key_size)
        copy(byte_offset(data, value_offset),
             byte_offset(load_pointer(byte_offset(source, 24)), index * value_size), value_size)
        store_pointer(output, row)
        following = index + step
    else:
        data = load_pointer(byte_offset(source, 24 if kind == VALUES else 16))
        copy(output, byte_offset(data, index * size), size)
        following = index + step
    store_integer(byte_offset(state, INDEX), following)
    return 1


@_runtime
def advance_buffered(state: Pointer, output: Pointer, context: Pointer) -> int:
    # Recursive advancement may release the state's fields. Root the captured
    # sources/cache/fill independently, including the partially populated row.
    source = load_pointer(byte_offset(state, SOURCE))
    children = load_pointer(byte_offset(state, CHILDREN))
    saved = load_pointer(byte_offset(state, CALLBACK_VALUE))
    longest = load_integer(state) == ZIP_LONGEST
    count = load_integer(byte_offset(state, COUNT))
    if longest and load_integer(byte_offset(state, LIMIT)) == 0:
        return 0 if load_integer(byte_offset(state, INDEX)) != 0 else finish(state)
    row = allocate_row(state, count) if longest else null()
    if longest and is_null(row):
        return -1
    if longest:
        store_integer(byte_offset(state, INDEX), load_integer(byte_offset(state, INDEX)) + 1)
    frame = stack_buffer(FRAME_SIZE)
    values = stack_buffer(40)
    slots = stack_buffer(40)
    store_pointer(values, state)
    store_pointer(byte_offset(values, 8), source)
    store_pointer(byte_offset(values, 16), children)
    store_pointer(byte_offset(values, 24), saved)
    store_pointer(byte_offset(values, 32), row)
    index = 0
    while index < 5:
        store_pointer(byte_offset(slots, index * 8), byte_offset(values, index * 8))
        index += 1
    if not is_null(context):
        push_frame(load_pointer(byte_offset(context, 8)), frame, slots, 5)
    result = (fill_longest(state, output, row, children, saved, context) if longest
              else fill_cycle(state, output, source, children, context))
    if longest:
        depth = load_integer(byte_offset(state, INDEX)) - 1
        store_integer(byte_offset(state, INDEX), depth)
        if depth == 0 and load_integer(byte_offset(state, LIMIT)) == 0:
            finish(state)
    if not is_null(context) and not try_pop_frame(load_pointer(byte_offset(context, 8)), frame):
        trap()
    return result


@_runtime
def fill_cycle(state: Pointer, output: Pointer, source: Pointer, saved: Pointer, context: Pointer) -> int:
    size = load_integer(byte_offset(state, ITEM_SIZE))
    if not is_null(source):
        # Fetch into the caller's rooted output before growing the saved list.
        # The allocator cannot call Python or collect; append may fail after
        # consuming this item, but does not publish an uninitialized cache slot.
        status = consume_stop(advance_context(source, output, context), context)
        if status < 0:
            return status
        if status != 0:
            slot = append_slot(load_pointer(byte_offset(state, ARENA)), saved, size)
            if is_null(slot):
                return -1
            copy(slot, output, size)
            # A nested advance can finish an empty cache while this fetch is
            # still in flight. Publishing its item makes that cache live again.
            store_pointer(byte_offset(state, CHILDREN), saved)
            store_integer(byte_offset(state, EXHAUSTED), 0)
            return 1
        store_pointer(byte_offset(state, SOURCE), null())
    length = load_integer(saved)
    if length == 0:
        return finish(state)
    index = load_integer(byte_offset(state, INDEX))
    copy(output, byte_offset(load_pointer(byte_offset(saved, ITEMS_OFFSET)), index * size), size)
    store_integer(byte_offset(state, INDEX), 0 if index + 1 == length else index + 1)
    return 1


@_runtime
def fill_longest(state: Pointer, output: Pointer, row: Pointer, children: Pointer,
                 fillvalue: Pointer, context: Pointer) -> int:
    count = load_integer(byte_offset(state, COUNT))
    offsets = load_pointer(byte_offset(state, OFFSETS))
    data = load_pointer(byte_offset(row, ITEMS_OFFSET))
    position = 0
    while position < count:
        slot = byte_offset(children, position * 8)
        child = load_pointer(slot)
        offset = load_integer(byte_offset(offsets, position * 8))
        destination = byte_offset(data, offset)
        status = consume_stop(advance_context(child, destination, context), context) if not is_null(child) else 0
        if status < 0:
            store_integer(byte_offset(state, LIMIT), 0)
            return status
        if status == 0:
            if not is_null(child):
                # Each in-flight visit accounts for its captured child, even
                # if a nested call exhausted it. CPython permits this counter
                # to become negative and then continues yielding fill rows.
                active = load_integer(byte_offset(state, LIMIT)) - 1
                store_integer(byte_offset(state, LIMIT), active)
                if active == 0:
                    return 0
                store_pointer(slot, null())
            # The saved fill row has the same heterogeneous layout as output.
            # Restore after exhaustion: a cursor may have touched its output
            # before reporting no value. The final offset is the row size.
            end = load_integer(byte_offset(offsets, (position + 1) * 8))
            copy(destination, byte_offset(fillvalue, offset), end - offset)
        position += 1
    store_pointer(output, row)
    return 1


@_runtime
def advance_row(state: Pointer, output: Pointer, context: Pointer) -> int:
    kind = load_integer(state)
    count = load_integer(byte_offset(state, COUNT))
    if kind == ZIP and count == 0:
        return finish(state)
    row = allocate_row(state, 2 if kind == ENUMERATE or kind == PAIRWISE else count)
    if is_null(row):
        return -1
    frame = stack_buffer(FRAME_SIZE)
    values = stack_buffer(32)
    slots = stack_buffer(32)
    store_pointer(values, row)
    store_pointer(byte_offset(values, 8), state)
    store_pointer(slots, values)
    store_pointer(byte_offset(slots, 8), byte_offset(values, 8))
    root_count = 2
    if kind == PAIRWISE or kind == BATCHED:
        # A reentrant child can finish this adapter and release its fields.
        # Keep the pointers used by this in-flight advancement independently.
        store_pointer(byte_offset(values, 16), load_pointer(byte_offset(state, SOURCE)))
        store_pointer(byte_offset(values, 24), load_pointer(byte_offset(state, CALLBACK_VALUE)))
        store_pointer(byte_offset(slots, 16), byte_offset(values, 16))
        store_pointer(byte_offset(slots, 24), byte_offset(values, 24))
        root_count = 4
    if not is_null(context):
        push_frame(load_pointer(byte_offset(context, 8)), frame, slots, root_count)
    result = fill_row(state, output, row, context)
    if not is_null(context):
        if not try_pop_frame(load_pointer(byte_offset(context, 8)), frame):
            trap()
    return result


@_runtime
def fill_row(state: Pointer, output: Pointer, row: Pointer, context: Pointer) -> int:
    kind = load_integer(state)
    count = load_integer(byte_offset(state, COUNT))
    data = load_pointer(byte_offset(row, ITEMS_OFFSET))
    offsets = load_pointer(byte_offset(state, OFFSETS))
    if kind == PAIRWISE or kind == BATCHED:
        return fill_group(state, output, row, context)
    if kind == ENUMERATE:
        child = load_pointer(byte_offset(state, SOURCE))
        status = advance_context(child, byte_offset(data, load_integer(offsets)), context)
        if status == 0:
            # An adapter may still advance shared children after StopIteration.
            # Only concrete, permanently exhausted children can be released.
            return finish(state) if load_integer(byte_offset(child, EXHAUSTED)) != 0 else 0
        if status < 0:
            return status
        if load_integer(byte_offset(state, LIMIT)) != 0:
            return -3
        # Advancing the child may recursively advance this same enumerate.
        index = load_integer(byte_offset(state, INDEX))
        store_integer(data, index)
        if index == 9223372036854775807:
            store_integer(byte_offset(state, LIMIT), 1)
        else:
            store_integer(byte_offset(state, INDEX), index + 1)
    else:
        children = load_pointer(byte_offset(state, CHILDREN))
        strict = load_integer(byte_offset(state, STRICT)) != 0
        position = 0
        while position < count:
            child = load_pointer(byte_offset(children, position * 8))
            status = advance_context(child, byte_offset(data, load_integer(byte_offset(offsets, position * 8))), context)
            if strict:
                status = consume_stop(status, context)
            if status < 0:
                return status
            if status == 0:
                if not strict:
                    # Each attempt still visits preceding shared cursors,
                    # even when a later child has already been exhausted.
                    return 0
                if position != 0:
                    return -5 - position * 2
                position = 1
                while position < count:
                    child = load_pointer(byte_offset(children, position * 8))
                    status = advance_context(child, byte_offset(data, load_integer(byte_offset(offsets, position * 8))), context)
                    status = consume_stop(status, context)
                    if status < 0:
                        return status
                    if status != 0:
                        return -6 - position * 2
                    position += 1
                return 0
            position += 1
    store_pointer(output, row)
    return 1


@_runtime
def advance_slice(state: Pointer, output: Pointer, context: Pointer) -> int:
    source = load_pointer(byte_offset(state, SOURCE))
    # Nested advancement may finish the slice and release SOURCE while this
    # invocation still needs it. Root the captured cursor, not just the state.
    frame = stack_buffer(FRAME_SIZE)
    values = stack_buffer(16)
    slots = stack_buffer(16)
    store_pointer(values, source)
    store_pointer(byte_offset(values, 8), state)
    store_pointer(slots, values)
    store_pointer(byte_offset(slots, 8), byte_offset(values, 8))
    if not is_null(context):
        push_frame(load_pointer(byte_offset(context, 8)), frame, slots, 2)
    result = fill_slice(state, source, output, context)
    if not is_null(context):
        if not try_pop_frame(load_pointer(byte_offset(context, 8)), frame):
            trap()
    return result


@_runtime
def fill_slice(state: Pointer, source: Pointer, output: Pointer, context: Pointer) -> int:
    skip = load_integer(byte_offset(state, COUNT))
    stop = load_integer(byte_offset(state, LIMIT))
    # Fully consuming islice advances to max(start, stop), even when start is
    # beyond stop. Reaching stop must not consume a following source value.
    while skip > 0:
        status = advance_context(source, output, context)
        if status <= 0:
            finish(state)
            return status
        # COUNT is the signed distance to the next selection. Reload after
        # callbacks: nested selections advance that target as well as consuming
        # input. A negative distance records consumption beyond the target.
        skip = load_integer(byte_offset(state, COUNT)) - 1
        stop = load_integer(byte_offset(state, LIMIT))
        stop = stop - 1 if stop > 0 else stop
        store_integer(byte_offset(state, COUNT), skip)
        store_integer(byte_offset(state, LIMIT), stop)
    if stop == 0:
        return finish(state)
    status = advance_context(source, output, context)
    if status <= 0:
        finish(state)
        return status
    # Remaining distances avoid overflowing absolute indexes on unbounded
    # streams. A finite stop also caps the final skipped distance.
    skip = load_integer(byte_offset(state, COUNT))
    step = load_integer(byte_offset(state, STEP))
    stride = step - 1
    stop = load_integer(byte_offset(state, LIMIT))
    stop = stop - 1 if stop > 0 else stop
    if stop >= 0:
        # Cap before adding: reentry can leave another selection's skip pending.
        skip = stop if skip > stop - stride else skip + stride
    else:
        # CPython resets an overflowing selection target to its -1 stop
        # sentinel. Track that target separately from consumption distances;
        # nested yields can reach it even on a short source with a huge stride.
        target = load_integer(byte_offset(state, INDEX))
        if target > 9223372036854775807 - step:
            skip = skip - target - 2
            target = -1
        else:
            skip += stride
            target += step
        store_integer(byte_offset(state, INDEX), target)
    store_integer(byte_offset(state, COUNT), skip)
    store_integer(byte_offset(state, LIMIT), stop)
    return 1


@_runtime
def fill_group(state: Pointer, output: Pointer, row: Pointer, context: Pointer) -> int:
    kind = load_integer(state)
    source = load_pointer(byte_offset(state, SOURCE))
    size = load_integer(byte_offset(state, ITEM_SIZE))
    data = load_pointer(byte_offset(row, ITEMS_OFFSET))
    if kind == PAIRWISE:
        previous = load_pointer(byte_offset(state, CALLBACK_VALUE))
        if load_integer(byte_offset(state, INDEX)) == 0:
            status = advance_context(source, previous, context)
            if status <= 0:
                finish(state)
                return status
            store_integer(byte_offset(state, INDEX), 1)
        copy(data, previous, size)
        following = byte_offset(data, load_integer(load_pointer(byte_offset(state, OFFSETS))))
        status = advance_context(source, following, context)
        if status <= 0:
            finish(state)
            return status
        copy(previous, following, size)
    else:
        count = load_integer(byte_offset(state, COUNT))
        position = 0
        while position < count:
            status = consume_stop(advance_context(source, byte_offset(data, position * size), context), context)
            if status <= 0:
                if status < 0 or position == 0:
                    finish(state)
                    return status
                if load_integer(byte_offset(state, STRICT)) != 0:
                    finish(state)
                    return INCOMPLETE_BATCH
                # A partial non-strict batch does not prove permanent child
                # exhaustion: map/filter callbacks may resume on the next pull.
                # A concrete child can prove exhaustion, allowing the final
                # partial row to release its source without an extra next().
                if load_integer(byte_offset(source, EXHAUSTED)) != 0:
                    finish(state)
                store_integer(row, position)
                break
            position += 1
    store_pointer(output, row)
    return 1


@_runtime
def create_pool(arena: Pointer, allocator: Pointer, owner: Pointer, mode: int,
                pools: Pointer, pool_count: int, width: int, item_size: int) -> Pointer:
    if width < 0 or width > 1152921504606846975 or item_size <= 0:
        return null()
    if width > _positive_quotient(9223372036854775759, item_size):
        return null()
    state = create(arena, allocator, owner, POOLED, pools, 0, pool_count, mode, item_size)
    if is_null(state):
        return null()
    store_integer(byte_offset(state, COUNT), width)
    store_integer(byte_offset(state, ROW_SIZE), width * item_size)
    length = 0
    position = 0
    while position < pool_count:
        length = load_integer(load_pointer(byte_offset(pools, position * 8)))
        if width > 0 and length == 0:
            finish(state)
        position += 1
    if mode != PRODUCT and mode != REPLACEMENT and width > length:
        finish(state)
    if load_integer(byte_offset(state, EXHAUSTED)) != 0:
        return state
    count = length if mode == PERMUTATIONS else width
    if count > 1152921504606846975:
        return null()
    indices = allocate_collection(arena, allocator, owner, count * 8)
    if is_null(indices):
        return null()
    store_pointer(byte_offset(state, OFFSETS), indices)
    position = 0
    while position < count:
        store_integer(byte_offset(indices, position * 8),
                      position if mode == COMBINATIONS or mode == PERMUTATIONS else 0)
        position += 1
    if mode == PERMUTATIONS:
        cycles = allocate_collection(arena, allocator, owner, width * 8)
        if is_null(cycles):
            return null()
        store_pointer(byte_offset(state, CHILDREN), cycles)
        position = 0
        while position < width:
            store_integer(byte_offset(cycles, position * 8), length - position)
            position += 1
    return state


@_runtime
def advance_pool(state: Pointer, output: Pointer) -> int:
    width = load_integer(byte_offset(state, COUNT))
    # Allocate before changing indices, so a failed allocation can retry the
    # same row. Every published tuple owns its payload; earlier rows stay live.
    row = allocate_row(state, width)
    if is_null(row):
        return -1
    pools = load_pointer(byte_offset(state, SOURCE))
    indices = load_pointer(byte_offset(state, OFFSETS))
    mode = load_integer(byte_offset(state, STEP))
    count = load_integer(byte_offset(state, LIMIT))
    if load_integer(byte_offset(state, INDEX)) != 0:
        if mode == PRODUCT:
            available = product_advance(indices, pools, count, width)
        else:
            length = load_integer(load_pointer(pools))
            if mode == PERMUTATIONS:
                available = permutations_advance(indices, load_pointer(byte_offset(state, CHILDREN)), length, width)
            else:
                available = combinations_advance(indices, length, width, mode == REPLACEMENT)
        if not available:
            store_pointer(byte_offset(state, OFFSETS), null())
            return finish(state)
    store_integer(byte_offset(state, INDEX), 1)
    data = load_pointer(byte_offset(row, ITEMS_OFFSET))
    size = load_integer(byte_offset(state, ITEM_SIZE))
    # Fixed product rows may mix field layouts. Other pooled iterators retain
    # the compact homogeneous stride and do not need a descriptor.
    layout = load_pointer(byte_offset(state, CALLBACK_VALUE))
    position = 0
    while position < width:
        pool_index = position - _positive_quotient(position, count) * count if mode == PRODUCT else 0
        pool = load_pointer(byte_offset(pools, pool_index * 8))
        index = load_integer(byte_offset(indices, position * 8))
        offset = position * size
        if not is_null(layout):
            size = load_integer(byte_offset(layout, pool_index * 8))
            offset = load_integer(byte_offset(layout, (count + position) * 8))
        copy(byte_offset(data, offset),
             byte_offset(load_pointer(byte_offset(pool, ITEMS_OFFSET)), index * size), size)
        position += 1
    store_pointer(output, row)
    return 1


@_runtime
def tee_block(arena: Pointer, allocator: Pointer, owner: Pointer, source: Pointer, size: int) -> Pointer:
    block = allocate_collection(arena, allocator, owner, TEE_DATA + TEE_CAPACITY * size)
    if not is_null(block):
        fill(block, int8(0), TEE_DATA + TEE_CAPACITY * size)
        store_pointer(byte_offset(block, TEE_SOURCE), source)
    return block


@_runtime
def create_tee(arena: Pointer, allocator: Pointer, owner: Pointer,
               source: Pointer, count: int, size: int) -> Pointer:
    return create_typed_tee(arena, allocator, owner, source, count, size, allocator)


@_runtime
def create_typed_tee(arena: Pointer, allocator: Pointer, owner: Pointer,
                     source: Pointer, count: int, size: int, block_allocator: Pointer) -> Pointer:
    if count < 0 or count > 1152921504606846975:
        return null()
    row = new_tuple(arena, allocator, owner, count * 8, count)
    if is_null(row) or count == 0:
        return row
    index = 0
    if load_integer(source) == TEE:
        block = load_pointer(byte_offset(source, SOURCE))
        index = load_integer(byte_offset(source, INDEX))
    else:
        block = tee_block(arena, block_allocator, owner, source, size)
    if is_null(block):
        return null()
    data = load_pointer(byte_offset(row, ITEMS_OFFSET))
    position = 0
    while position < count:
        cursor = create(arena, allocator, owner, TEE, block, index, 0, 1, size)
        if is_null(cursor):
            return null()
        store_pointer(byte_offset(cursor, OFFSETS), block_allocator)
        store_pointer(byte_offset(data, position * 8), cursor)
        position += 1
    return row


@_runtime
def advance_tee(state: Pointer, output: Pointer, context: Pointer) -> int:
    block = load_pointer(byte_offset(state, SOURCE))
    index = load_integer(byte_offset(state, INDEX))
    size = load_integer(byte_offset(state, ITEM_SIZE))
    if index == TEE_CAPACITY:
        following = load_pointer(byte_offset(block, TEE_NEXT))
        if is_null(following):
            following = tee_block(load_pointer(byte_offset(state, ARENA)), load_pointer(byte_offset(state, OFFSETS)),
                                  load_pointer(byte_offset(state, OWNER)), load_pointer(byte_offset(block, TEE_SOURCE)), size)
            if is_null(following):
                return -1
            store_pointer(byte_offset(block, TEE_NEXT), following)
        block = following
        index = 0
        store_pointer(byte_offset(state, SOURCE), block)
        store_integer(byte_offset(state, INDEX), 0)
    slot = byte_offset(block, TEE_DATA + index * size)
    if index == load_integer(byte_offset(block, TEE_COUNT)):
        if load_integer(byte_offset(block, TEE_RUNNING)) != 0:
            return TEE_REENTRY
        store_integer(byte_offset(block, TEE_RUNNING), 1)
        frame = stack_buffer(FRAME_SIZE)
        values = stack_buffer(16)
        slots = stack_buffer(16)
        store_pointer(values, state)
        store_pointer(byte_offset(values, 8), block)
        store_pointer(slots, values)
        store_pointer(byte_offset(slots, 8), byte_offset(values, 8))
        if not is_null(context):
            push_frame(load_pointer(byte_offset(context, 8)), frame, slots, 2)
        status = consume_stop(advance_context(load_pointer(byte_offset(block, TEE_SOURCE)), slot, context), context)
        store_integer(byte_offset(block, TEE_RUNNING), 0)
        if not is_null(context):
            if not try_pop_frame(load_pointer(byte_offset(context, 8)), frame):
                trap()
        if status <= 0:
            fill(slot, int8(0), size)
            return status
        store_integer(byte_offset(block, TEE_COUNT), index + 1)
    copy(output, slot, size)
    store_integer(byte_offset(state, INDEX), index + 1)
    return 1


@_runtime
def create_group(arena: Pointer, allocator: Pointer, owner: Pointer, source: Pointer,
                 item_size: int, key_size: int) -> Pointer:
    # Raw callers without typed layout metadata keep conservative workspace
    # allocation. The same state machine still owns publication and retry.
    return create_typed_group(arena, allocator, owner, source, item_size, key_size, allocator, -1)


@native_operation("memory.group.header")
def allocate_group_workspace(arena: Pointer, allocator: Pointer, owner: Pointer, size: int) -> Pointer:
    return allocate_collection(arena, allocator, owner, size)


@_runtime
def trace_group_workspace(value: Pointer, index: int) -> Pointer:
    if index == 0:
        return load_pointer(byte_offset(value, GROUP_ACTIVE))
    layout = load_integer(byte_offset(value, GROUP_LAYOUT))
    stride = load_integer(value)
    code = (layout & GROUP_SLOT_MASK if index == 1 else
            _positive_quotient(layout, GROUP_KEY_FACTOR) & GROUP_SLOT_MASK)
    if code == GROUP_SCALAR:
        return null()
    # Each typed slot is scalar (0), a reference (1), or tagged (2), whose
    # reference candidate lives after its discriminator. Key slots share code.
    offset = GROUP_VALUES + (index - 1) * stride + (GROUP_TAGGED_PAYLOAD if code == GROUP_TAGGED else 0)
    return load_pointer(byte_offset(value, offset))


@_runtime
def create_typed_group(arena: Pointer, allocator: Pointer, owner: Pointer, source: Pointer,
                       item_size: int, key_size: int, key_allocator: Pointer, layout: int) -> Pointer:
    state = create(arena, allocator, owner, GROUPBY, source, 0, 0, 1, item_size)
    if is_null(state):
        return null()
    # Word padding makes every conservative scratch root a complete, aligned
    # word, including boolean and narrow portable scalar items/keys.
    stride = _positive_quotient(max(item_size, key_size) + 7, 8) * 8
    size = GROUP_VALUES + 3 * stride
    data = (allocate_collection(arena, allocator, owner, size) if layout < 0
            else allocate_group_workspace(arena, allocator, owner, size))
    if is_null(data):
        return null()
    fill(data, int8(0), size)
    store_integer(data, stride)
    store_pointer(byte_offset(data, GROUP_KEY_ALLOCATOR), key_allocator)
    store_integer(byte_offset(data, GROUP_LAYOUT), layout)
    store_pointer(byte_offset(state, CHILDREN), data)
    store_integer(byte_offset(state, COUNT), key_size)
    return state


@_runtime
def group_fetch(parent: Pointer, scratch: Pointer, context: Pointer) -> int:
    data = load_pointer(byte_offset(parent, CHILDREN))
    stride = load_integer(data)
    fill(scratch, int8(0), 2 * stride)
    status = consume_stop(advance_context(load_pointer(byte_offset(parent, SOURCE)), scratch, context), context)
    if status <= 0:
        return status
    status = invoke_checked(load_pointer(byte_offset(parent, ADVANCE)),
                              load_pointer(context), load_pointer(byte_offset(context, 8)),
                              load_pointer(byte_offset(context, 16)), parent, scratch)
    if status == 1:
        copy(byte_offset(data, GROUP_VALUES), scratch, load_integer(byte_offset(parent, ITEM_SIZE)))
        copy(byte_offset(data, GROUP_VALUES + stride), byte_offset(scratch, stride), load_integer(byte_offset(parent, COUNT)))
        store_integer(byte_offset(parent, INDEX), 1)
        store_integer(byte_offset(parent, STEP), 0)
    return status


@_runtime
def group_compare(parent: Pointer, target: Pointer, context: Pointer) -> int:
    data = load_pointer(byte_offset(parent, CHILDREN))
    return invoke_checked(load_pointer(byte_offset(parent, OFFSETS)),
                            load_pointer(context), load_pointer(byte_offset(context, 8)),
                            load_pointer(byte_offset(context, 16)), target,
                            byte_offset(data, GROUP_VALUES + load_integer(data)))


@_runtime
def fill_groupby(parent: Pointer, output: Pointer, scratch: Pointer, context: Pointer) -> int:
    data = load_pointer(byte_offset(parent, CHILDREN))
    stride = load_integer(data)
    # Advancing the parent invalidates its previous group before consuming or
    # comparing anything, including when this attempt subsequently raises.
    store_pointer(byte_offset(data, GROUP_ACTIVE), null())
    while True:
        if load_integer(byte_offset(parent, INDEX)) != 0:
            if load_integer(byte_offset(parent, LIMIT)) == 0:
                break
            # The opening key is the target itself. Preserve that identity
            # without comparing unboxed NaNs, which are not equal to themselves.
            if load_integer(byte_offset(parent, STEP)) == 0:
                status = group_compare(parent, byte_offset(data, GROUP_VALUES + 2 * stride), context)
                if status <= 0:
                    return status
                if status == 1:
                    break
        status = group_fetch(parent, scratch, context)
        if status <= 0:
            return status
    arena = load_pointer(byte_offset(parent, ARENA))
    allocator = load_pointer(byte_offset(parent, ALLOCATOR))
    owner = load_pointer(byte_offset(parent, OWNER))
    size = load_integer(byte_offset(parent, ITEM_SIZE))
    key_size = load_integer(byte_offset(parent, COUNT))
    cursor = create(arena, allocator, owner, GROUPER, parent, 0, 0, 1, size)
    if is_null(cursor):
        return -1
    target = allocate_collection(arena, load_pointer(byte_offset(data, GROUP_KEY_ALLOCATOR)), owner, stride)
    if is_null(target):
        return -1
    fill(target, int8(0), stride)
    store_pointer(byte_offset(cursor, CALLBACK_VALUE), target)
    row = allocate_row(parent, 2)
    if is_null(row):
        return -1
    # Publish only after every allocation succeeds. A failed allocation leaves
    # the pending key/value available to a subsequent parent advance.
    copy(target, byte_offset(data, GROUP_VALUES + stride), key_size)
    copy(byte_offset(data, GROUP_VALUES + 2 * stride), target, key_size)
    store_integer(byte_offset(parent, LIMIT), 1)
    store_integer(byte_offset(parent, STEP), 1)
    store_pointer(byte_offset(data, GROUP_ACTIVE), cursor)
    items = load_pointer(byte_offset(row, ITEMS_OFFSET))
    copy(items, target, key_size)
    store_pointer(byte_offset(items, load_integer(byte_offset(parent, STRICT))), cursor)
    store_pointer(output, row)
    return 1


@_runtime
def fill_grouper(state: Pointer, output: Pointer, scratch: Pointer, context: Pointer) -> int:
    parent = load_pointer(byte_offset(state, SOURCE))
    data = load_pointer(byte_offset(parent, CHILDREN))
    if not same_address(state, load_pointer(byte_offset(data, GROUP_ACTIVE))):
        return 0
    if load_integer(byte_offset(parent, INDEX)) == 0:
        status = group_fetch(parent, scratch, context)
        if status <= 0:
            return status
    # Always yield the item that opened this group, even for non-reflexive keys.
    # Later items still use normal equality, including its reentrant callbacks.
    if load_integer(byte_offset(parent, STEP)) == 0:
        status = group_compare(parent, load_pointer(byte_offset(state, CALLBACK_VALUE)), context)
        if status <= 0:
            return status
        if status == 1 or load_integer(byte_offset(parent, INDEX)) == 0:
            return 0
    copy(output, byte_offset(data, GROUP_VALUES), load_integer(byte_offset(parent, ITEM_SIZE)))
    fill(byte_offset(data, GROUP_VALUES), int8(0), 2 * load_integer(data))
    store_integer(byte_offset(parent, INDEX), 0)
    store_integer(byte_offset(parent, STEP), 0)
    return 1


@_runtime
def advance_group(state: Pointer, output: Pointer, context: Pointer) -> int:
    if is_null(context):
        return CALLBACK_ERROR
    parent = state if load_integer(state) == GROUPBY else load_pointer(byte_offset(state, SOURCE))
    stride = load_integer(load_pointer(byte_offset(parent, CHILDREN)))
    words = 1 + _positive_quotient(2 * stride, 8)
    frame = stack_buffer(FRAME_SIZE)
    values = stack_buffer(words * 8)
    slots = stack_buffer(words * 8)
    fill(values, int8(0), words * 8)
    store_pointer(values, state)
    index = 0
    while index < words:
        store_pointer(byte_offset(slots, index * 8), byte_offset(values, index * 8))
        index += 1
    push_frame(load_pointer(byte_offset(context, 8)), frame, slots, words)
    scratch = byte_offset(values, 8)
    if load_integer(state) == GROUPBY:
        result = fill_groupby(state, output, scratch, context)
    else:
        result = fill_grouper(state, output, scratch, context)
    if not try_pop_frame(load_pointer(byte_offset(context, 8)), frame):
        trap()
    return result


@cache
def compiled_runtime():
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.iterator.new": create, "pyjs.iterator.finish": finish, "pyjs.iterator.pooled": create_pool,
                            "pyjs.iterator.tee": create_tee, "pyjs.iterator.tee.typed": create_typed_tee,
                            "pyjs.iterator.group": create_group, "pyjs.iterator.group.typed": create_typed_group,
                            "pyjs.iterator.group.trace": trace_group_workspace,
                            "pyjs.iterator.next": advance,
                            "pyjs.iterator.next.context": advance_context,
                            "pyjs.iterator.iter": iterate, "pyjs.iterator.identity": identity,
                            "pyjs.iterator.control": control,
                            "pyjs.iterator.consume.stop": consume_stop},
                           dependencies={"pyjs.collection.try.alloc": allocate_collection,
                                         "pyjs.tuple.new": new_tuple})
