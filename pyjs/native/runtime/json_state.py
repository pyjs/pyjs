"""Call-local iterative JSON traversal with reusable sibling frames.

Generated callbacks emit one container item, schedule its child, and return.
Sorting may call application comparisons. A managed root vector keeps each
pending input and entry snapshot alive until its frame is popped. Scratch
frames themselves remain unmanaged and are released on every exit.
"""

import ctypes
from functools import cache

from pyjs import int8
from pyjs.decorators import native_operation

from .algorithms import _runtime
from .arena import BUFFER_DATA_OFFSET, allocate_in_arena, new_buffer, resize_buffer
from .identity import get, put, remove
from .ordering import merge_sort
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    fill,
    is_null,
    load_bool,
    load_integer,
    load_pointer,
    null,
    store_integer,
    store_pointer,
)
from .sequences import ITEMS_OFFSET, reserve, truncate


class _State(ctypes.Structure):
    _fields_ = [("head", ctypes.c_void_p), ("free", ctypes.c_void_p),
                ("scratch", ctypes.c_void_p), ("active", ctypes.c_void_p),
                ("check_circular", ctypes.c_bool), ("ensure_ascii", ctypes.c_bool),
                ("allow_nan", ctypes.c_bool), ("sort_keys", ctypes.c_bool),
                ("skipkeys", ctypes.c_bool),
                ("roots", ctypes.c_void_p),
                ("indent", ctypes.c_void_p), ("indent_count", ctypes.c_int64),
                ("item_separator", ctypes.c_void_p), ("key_separator", ctypes.c_void_p)]


class _Frame(ctypes.Structure):
    _fields_ = [("parent", ctypes.c_void_p), ("callback", ctypes.c_void_p),
                ("value", ctypes.c_void_p), ("index", ctypes.c_int64),
                ("depth", ctypes.c_int64), ("indices", ctypes.c_void_p),
                ("snapshot", ctypes.c_void_p),
                ("written", ctypes.c_int64),
                ("sort_owner", ctypes.c_void_p), ("sort_capacity", ctypes.c_int64)]


STATE_SIZE = ctypes.sizeof(_State)
FRAME_SIZE = ctypes.sizeof(_Frame)
FREE = _State.free.offset
SCRATCH = _State.scratch.offset
ACTIVE = _State.active.offset
CHECK_CIRCULAR = _State.check_circular.offset
ROOTS = _State.roots.offset
CALLBACK = _Frame.callback.offset
VALUE = _Frame.value.offset
INDEX = _Frame.index.offset
DEPTH = _Frame.depth.offset
INDICES = _Frame.indices.offset
SNAPSHOT = _Frame.snapshot.offset
WRITTEN = _Frame.written.offset
SORT_OWNER = _Frame.sort_owner.offset
SORT_CAPACITY = _Frame.sort_capacity.offset


@_runtime
def push(state: Pointer, callback: Pointer, value: Pointer, depth: int) -> int8:
    """Return success=0, cycle=1, depth=2 or allocation failure=3."""
    active = load_pointer(byte_offset(state, ACTIVE))
    checked = load_bool(byte_offset(state, CHECK_CIRCULAR))
    if checked and not is_null(get(active, value)):
        return int8(1)
    if depth >= 1000:
        return int8(2)
    scratch = load_pointer(byte_offset(state, SCRATCH))
    roots = load_pointer(byte_offset(state, ROOTS))
    count = 0
    if not is_null(roots):
        count = load_integer(roots)
        if not reserve(scratch, roots, count + 2, 8):
            return int8(3)
    frame = load_pointer(byte_offset(state, FREE))
    if is_null(frame):
        frame = allocate_in_arena(scratch, FRAME_SIZE, 8)
        if is_null(frame):
            return int8(3)
        fill(frame, int8(0), FRAME_SIZE)
    else:
        store_pointer(byte_offset(state, FREE), load_pointer(frame))
    if checked and not put(scratch, active, value, frame):
        return int8(3)
    if not is_null(roots):
        slots = load_pointer(byte_offset(roots, ITEMS_OFFSET))
        store_pointer(byte_offset(slots, count * 8), value)
        store_pointer(byte_offset(slots, (count + 1) * 8), null())
        store_integer(roots, count + 2)
    store_pointer(frame, load_pointer(state))
    store_pointer(byte_offset(frame, CALLBACK), callback)
    store_pointer(byte_offset(frame, VALUE), value)
    store_integer(byte_offset(frame, INDEX), 0)
    store_integer(byte_offset(frame, DEPTH), depth)
    store_pointer(byte_offset(frame, INDICES), null())
    store_pointer(byte_offset(frame, SNAPSHOT), null())
    store_integer(byte_offset(frame, WRITTEN), 0)
    store_pointer(state, frame)
    return int8(0)


@_runtime
def pop(state: Pointer) -> None:
    frame = load_pointer(state)
    if load_bool(byte_offset(state, CHECK_CIRCULAR)):
        remove(load_pointer(byte_offset(state, ACTIVE)), load_pointer(byte_offset(frame, VALUE)))
    roots = load_pointer(byte_offset(state, ROOTS))
    if not is_null(roots):
        truncate(roots, load_integer(roots) - 2, 8)
    store_pointer(state, load_pointer(frame))
    free_slot = byte_offset(state, FREE)
    store_pointer(frame, load_pointer(free_slot))
    store_pointer(free_slot, frame)


@_runtime
def scalar_index(state: Pointer, frame: Pointer, keys: Pointer, length: int,
                 key_size: int, kind: int8, index: int, enabled: bool) -> int:
    """Reuse sibling scratch for callback-free scalar sorting; -1 means OOM.

    Records contain a padded scalar key and its original index. The input stays
    rooted and unchanged throughout this subtree; raw scratch needs no GC roots.
    Callback-capable encodings must use the separate entry snapshot path.
    """
    if not enabled or length < 2:
        return index
    owner = load_pointer(byte_offset(frame, SORT_OWNER))
    if index == 0:
        if length > 288230376151711743 or key_size < 1 or key_size > 8:
            return -1
        if length > load_integer(byte_offset(frame, SORT_CAPACITY)):
            if is_null(owner):
                owner = new_buffer(load_pointer(byte_offset(state, SCRATCH)), length * 32)
                if is_null(owner):
                    return -1
                store_pointer(byte_offset(frame, SORT_OWNER), owner)
            elif is_null(resize_buffer(owner, length * 32)):
                return -1
            store_integer(byte_offset(frame, SORT_CAPACITY), length)
        data = load_pointer(byte_offset(owner, BUFFER_DATA_OFFSET))
        current = 0
        while current < length:
            record = byte_offset(data, current * 16)
            copy(record, byte_offset(keys, current * key_size), key_size)
            store_integer(byte_offset(record, 8), current)
            current += 1
        merge_sort(data, length, 16, byte_offset(data, length * 16), kind, False)
    data = load_pointer(byte_offset(owner, BUFFER_DATA_OFFSET))
    return load_integer(byte_offset(data, index * 16 + 8))


@native_operation("memory.invoke")
def _step(callback: Pointer, arena: Pointer, heap: Pointer, error: Pointer,
          output: Pointer, state: Pointer, frame: Pointer) -> None:
    signature = ctypes.CFUNCTYPE(None, *([ctypes.c_void_p] * 6))
    signature(callback.address)(arena.address, heap.address, error.address,
                                output.address, state.address, frame.address)


@_runtime
def run(arena: Pointer, heap: Pointer, error: Pointer, output: Pointer, state: Pointer) -> None:
    while not load_bool(error):
        frame = load_pointer(state)
        if is_null(frame):
            return
        _step(load_pointer(byte_offset(frame, CALLBACK)), arena, heap, error, output, state, frame)


@cache
def compiled_runtime():
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.json.push": push, "pyjs.json.pop": pop, "pyjs.json.run": run,
                            "pyjs.json.scalar.index": scalar_index}, dependencies={
        "pyjs.arena.try.alloc": allocate_in_arena,
        "pyjs.arena.buffer.try.new": new_buffer,
        "pyjs.arena.buffer.try.resize": resize_buffer,
        "pyjs.collection.merge.sort": merge_sort,
        "pyjs.identity.get": get,
        "pyjs.identity.try.put": put,
        "pyjs.identity.remove": remove,
        "pyjs.list.try.reserve": reserve,
        "pyjs.list.truncate": truncate,
    })
