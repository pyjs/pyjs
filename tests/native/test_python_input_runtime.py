"""The same graph-copy algorithm runs as Python and compiled LLVM."""

import ctypes

import pytest

from pyjs.native.llvm import transpile_llvm_module
from pyjs.native.runtime import arena, collector, heap, identity, inputs, roots
from pyjs.native.runtime.pointers import Pointer, byte_offset, null
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def input_runtime(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm_module('''
        from pyjs.native import gc_pin
        def main(value: list[str]) -> str:
            gc_pin(value)
            return value[0]
    ''', target="library").llvm_ir)
    functions = {
        "pyjs.input.try.ownership": inputs.ownership_snapshot,
        "pyjs.input.try.copy": inputs.promote,
        "pyjs.identity.try.new": identity.new_map,
        "pyjs.arena.init": arena.initialize,
        "pyjs.arena.destroy": arena.destroy_arena,
        "pyjs.gc.init": collector.initialize,
        "pyjs.gc.try.alloc.described": heap.allocate_described,
        "pyjs.gc.destroy": roots.destroy_heap,
        "pyjs.gc.try.collect": collector.try_collect,
        "pyjs.gc.try.pin": roots.try_pin,
        "pyjs.gc.unpin": roots.unpin,
    }
    invoke = runtime_functions(functions, library)

    def call(name, *arguments):
        if name == "pyjs.input.try.promote":
            arena_pointer, heap_pointer, *_ = arguments
            owned = invoke("pyjs.input.try.ownership", arena_pointer, heap_pointer, True)
            assert owned.address
            return invoke("pyjs.input.try.copy", *arguments, owned)
        return invoke(name, *arguments)

    return call


class Node(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int64), ("next", ctypes.c_void_p),
                ("alias", ctypes.c_void_p)]


@pytest.mark.parametrize("length,has_data,valid", [
    (0, False, True), (3, True, True), (3, False, False),
    (-1, True, False), (2**63 - 1, True, False), (2**63 - 9, True, False),
])
def test_text_copy_coallocates_and_rejects_invalid_raw_lengths(input_runtime, length, has_data, valid):
    from pyjs.tooling.llvm import _LLVMString

    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    data = ctypes.create_string_buffer(b"a\x00b")
    source = _LLVMString(length, ctypes.addressof(data) if has_data else None)
    shape = inputs._Shape(ctypes.sizeof(source), 0, None, -1, text=True)
    try:
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        arguments = (arena_pointer, heap_pointer, memo, Pointer(ctypes.addressof(source)),
                     Pointer(ctypes.addressof(shape)), null())
        result = invoke("pyjs.input.try.promote", *arguments)
        assert bool(result.address) is valid
        if valid:
            copied = _LLVMString.from_address(result.address)
            assert copied.length == length
            assert copied.data == result.address + ctypes.sizeof(source)
            assert ctypes.string_at(copied.data, length) == b"a\x00b"[:length]
            assert invoke("pyjs.input.try.promote", *arguments).address == result.address
            assert managed.count == 1  # Repeated borrowed identities share the copy.
            assert invoke("pyjs.gc.try.pin", heap_pointer, result)
            invoke("pyjs.arena.destroy", arena_pointer)
            assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == 1
            invoke("pyjs.gc.unpin", heap_pointer, result)
        assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)


def test_copy_installs_shape_identity_but_preserves_owned_dynamic_identity(input_runtime):
    class Record(ctypes.Structure):
        _fields_ = [("identity", ctypes.c_void_p), ("number", ctypes.c_int64)]

    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    trusted, dynamic = ctypes.c_int64(1), ctypes.c_int64(2)
    shape = inputs._Shape(ctypes.sizeof(Record), 0, None, -1, False, ctypes.addressof(trusted))
    source = Record(0xBAD, 42)  # A forged borrowed word is never used as identity.
    try:
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        copied = invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                        Pointer(ctypes.addressof(source)), Pointer(ctypes.addressof(shape)), null())
        assert copied.address and copied.address != ctypes.addressof(source)
        result = Record.from_address(copied.address)
        assert (result.identity, result.number) == (ctypes.addressof(trusted), 42)
        assert source.identity == 0xBAD
        # The raw entry can receive an existing native subclass. Its identity
        # belongs to that object, not the declared base-shaped input slot.
        result.identity = ctypes.addressof(dynamic)
        again = invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                       copied, Pointer(ctypes.addressof(shape)), null())
        assert again.address == copied.address and result.identity == ctypes.addressof(dynamic)
        assert invoke("pyjs.gc.try.pin", heap_pointer, copied)
        invoke("pyjs.arena.destroy", arena_pointer)
        assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == 1
        invoke("pyjs.gc.unpin", heap_pointer, copied)
        assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)


def test_deep_copy_uses_a_worklist_without_python_or_native_recursion(input_runtime):
    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    count = 20000
    # Flat ctypes backing avoids creating a deep Python deallocation graph or
    # changing recursion limits. This same algorithm runs in CPython/O0/O2.
    source = (Node * count)()
    for index in range(count):
        child = ctypes.addressof(source[index + 1]) if index + 1 < count else 0
        source[index] = Node(index, child, child)
    shape = inputs._Shape(ctypes.sizeof(Node), 2, None, -1)
    fields = (inputs._Field * 2)(
        inputs._Field(Node.next.offset, ctypes.addressof(shape), -1, 0),
        inputs._Field(Node.alias.offset, ctypes.addressof(shape), -1, 0),
    )
    shape.fields = ctypes.addressof(fields)
    try:
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        copied = invoke("pyjs.input.try.copy", arena_pointer, heap_pointer, memo,
                        Pointer(ctypes.addressof(source)), Pointer(ctypes.addressof(shape)), null(), null())
        assert copied.address and managed.count == count
        cursor = copied.address
        for index in range(count):
            node = Node.from_address(cursor)
            assert cursor != ctypes.addressof(source[index])
            assert node.value == index and node.next == node.alias
            cursor = node.next
        assert cursor is None
        assert invoke("pyjs.gc.try.pin", heap_pointer, copied)
        invoke("pyjs.arena.destroy", arena_pointer)
        assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == count
        invoke("pyjs.gc.unpin", heap_pointer, copied)
        assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)


def test_inline_tagged_fields_copy_only_selected_references(input_runtime):
    from pyjs.tooling.llvm import _LLVMTagged

    class Parent(ctypes.Structure):
        _fields_ = [("length", ctypes.c_int64), ("data", ctypes.c_void_p), ("item", _LLVMTagged)]

    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    leaf_shape = inputs._Shape(ctypes.sizeof(Node), 0, None, -1)
    tag_field = inputs._Field(_LLVMTagged.value.offset, ctypes.addressof(leaf_shape), -1, 0, False, 4)
    tag_shape = inputs._Shape(ctypes.sizeof(_LLVMTagged), 1, ctypes.addressof(tag_field), -1, True)
    fields = (inputs._Field * 2)(
        inputs._Field(Parent.data.offset, ctypes.addressof(tag_shape), Parent.length.offset, ctypes.sizeof(_LLVMTagged)),
        inputs._Field(Parent.item.offset, ctypes.addressof(tag_shape), -1, 0),
    )
    shape = inputs._Shape(ctypes.sizeof(Parent), 2, ctypes.addressof(fields), -1)
    leaf = Node(42)
    # Both scalar words are invalid pointers if the selected-tag check is lost.
    values = (_LLVMTagged * 3)(_LLVMTagged(4, ctypes.addressof(leaf)),
                              _LLVMTagged(2, 2**64 - 1), _LLVMTagged(3, 0x7ff8000000000001))
    source = Parent(3, ctypes.addressof(values), _LLVMTagged(4, ctypes.addressof(leaf)))
    try:
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        result = invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                        Pointer(ctypes.addressof(source)), Pointer(ctypes.addressof(shape)), null())
        assert result.address
        copied = Parent.from_address(result.address)
        items = (_LLVMTagged * 3).from_address(copied.data)
        assert copied.data != source.data
        assert items[0].value == copied.item.value != ctypes.addressof(leaf)
        assert [(item.tag, item.value) for item in items[1:]] == [(item.tag, item.value) for item in values[1:]]
        leaf.value = 0
        assert Node.from_address(copied.item.value).value == 42
        assert managed.count == 3  # Parent, array and leaf; no boxes for inline slots.
        assert invoke("pyjs.gc.try.pin", heap_pointer, result)
        invoke("pyjs.arena.destroy", arena_pointer)
        assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == 3
        invoke("pyjs.gc.unpin", heap_pointer, result)
        assert invoke("pyjs.gc.try.collect", heap_pointer) and managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)


def test_ownership_snapshot_preserves_interiors_and_excludes_new_copies(input_runtime):
    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    shape = inputs._Shape(ctypes.sizeof(Node), 1, None, -1)
    field = inputs._Field(Node.next.offset, ctypes.addressof(shape), -1, 0)
    shape.fields = ctypes.addressof(field)
    try:
        allocation = invoke("pyjs.gc.try.alloc.described", heap_pointer, ctypes.sizeof(Node) + 8, null())
        child = byte_offset(allocation, 8)
        Node.from_address(child.address).value = 42
        parent = Node(7, child.address)
        owned = invoke("pyjs.input.try.ownership", arena_pointer, heap_pointer, True)
        snapshot = heap._Heap.from_address(owned.address)
        assert snapshot.count == 1 and snapshot.index and managed.index is None
        # A one-object snapshot needs two hash slots and one range pointer,
        # not the collector's additional mark-stack slot.
        assert arena._Chunk.from_address(storage.chunks).used == heap.HEAP_SIZE + collector.INDEX_SIZE + 3 * 8
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        copied = invoke("pyjs.input.try.copy", arena_pointer, heap_pointer, memo,
                        Pointer(ctypes.addressof(parent)), Pointer(ctypes.addressof(shape)), null(), owned)
        assert copied.address and copied.address != ctypes.addressof(parent)
        assert managed.count == 2 and snapshot.count == 1
        assert Node.from_address(copied.address).next == child.address
        assert invoke("pyjs.gc.try.pin", heap_pointer, copied)
        invoke("pyjs.arena.destroy", arena_pointer)
        assert invoke("pyjs.gc.try.collect", heap_pointer)
        assert managed.count == 2 and Node.from_address(child.address).value == 42
        invoke("pyjs.gc.unpin", heap_pointer, copied)
        assert invoke("pyjs.gc.try.collect", heap_pointer)
        assert managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)


def test_runtime_copy_preserves_graph_identity_and_gc_ownership(input_runtime):
    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    # A cycle exercises memo publication before recursion without depending on
    # recursive schema analysis, which is not yet part of the host Python ABI.
    shape = inputs._Shape(ctypes.sizeof(Node), 2, None, -1)
    fields = (inputs._Field * 2)(
        inputs._Field(Node.next.offset, ctypes.addressof(shape), -1, 0),
        inputs._Field(Node.alias.offset, ctypes.addressof(shape), -1, 0),
    )
    shape.fields = ctypes.addressof(fields)
    first, second = Node(10), Node(20)
    first.next = first.alias = ctypes.addressof(second)
    second.next = second.alias = ctypes.addressof(first)
    try:
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        copied = invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                        Pointer(ctypes.addressof(first)), Pointer(ctypes.addressof(shape)), null())
        assert copied.address != ctypes.addressof(first)
        retained = Node.from_address(copied.address)
        child = Node.from_address(retained.next)
        assert retained.next == retained.alias != ctypes.addressof(second)
        assert child.next == child.alias == copied.address
        first.value = second.value = 0
        assert (retained.value, child.value) == (10, 20)
        # Every root and read-only alias in a call uses the same memo.
        again = invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                       Pointer(ctypes.addressof(second)), Pointer(ctypes.addressof(shape)), null())
        assert again.address == retained.next
        # Reentrant native entry calls keep already-managed identities.
        owned = invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                       copied, Pointer(ctypes.addressof(shape)), null())
        assert owned.address == copied.address
        assert invoke("pyjs.gc.try.pin", heap_pointer, copied)
        invoke("pyjs.arena.destroy", arena_pointer)
        assert invoke("pyjs.gc.try.collect", heap_pointer)
        assert managed.count == 2 and child.next == copied.address
        invoke("pyjs.gc.unpin", heap_pointer, copied)
        assert invoke("pyjs.gc.try.collect", heap_pointer)
        assert managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_owned_and_borrowed_graphs_share_children(input_runtime, reverse):
    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    shape = inputs._Shape(ctypes.sizeof(Node), 1, None, -1)
    field = inputs._Field(Node.next.offset, ctypes.addressof(shape), -1, 0)
    shape.fields = ctypes.addressof(field)

    def promote(memo, address):
        return invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                      Pointer(address), Pointer(ctypes.addressof(shape)), null())

    try:
        original = Node(7)
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        child = promote(memo, ctypes.addressof(original))
        borrowed = Node(10, child.address)
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        addresses = [ctypes.addressof(borrowed), child.address]
        if reverse:
            addresses.reverse()
        copies = [promote(memo, address) for address in addresses]
        parent, direct = reversed(copies) if reverse else copies
        retained = Node.from_address(parent.address)
        assert retained.next == direct.address == child.address
        Node.from_address(direct.address).value = 99
        assert Node.from_address(retained.next).value == 99
        assert invoke("pyjs.gc.try.pin", heap_pointer, parent)
        invoke("pyjs.arena.destroy", arena_pointer)
        assert invoke("pyjs.gc.try.collect", heap_pointer)
        assert managed.count == 2
        assert Node.from_address(retained.next).value == 99
        invoke("pyjs.gc.unpin", heap_pointer, parent)
        assert invoke("pyjs.gc.try.collect", heap_pointer)
        assert managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)


@pytest.mark.parametrize("count,optional,valid", [(4, False, False), (-1, True, False),
                                                 (0, False, True), (4, True, True)])
def test_null_counted_buffers_require_empty_or_explicitly_optional_storage(input_runtime, count, optional, valid):
    invoke = input_runtime
    storage, managed = arena._Arena(), heap._Heap()
    arena_pointer, heap_pointer = Pointer(ctypes.addressof(storage)), Pointer(ctypes.addressof(managed))
    invoke("pyjs.arena.init", arena_pointer)
    invoke("pyjs.gc.init", heap_pointer)
    field = inputs._Field(Node.next.offset, None, Node.value.offset, 8, optional)
    shape = inputs._Shape(ctypes.sizeof(Node), 1, ctypes.addressof(field), -1)
    source = Node(count)
    try:
        memo = invoke("pyjs.identity.try.new", arena_pointer)
        result = invoke("pyjs.input.try.promote", arena_pointer, heap_pointer, memo,
                        Pointer(ctypes.addressof(source)), Pointer(ctypes.addressof(shape)), null())
        assert bool(result.address) is valid
        if valid:
            assert Node.from_address(result.address).next is None
        # Failure may leave unreachable partial copies; the next collection
        # must reclaim them, just like allocation failures during promotion.
        assert invoke("pyjs.gc.try.collect", heap_pointer)
        assert managed.count == 0
    finally:
        invoke("pyjs.arena.destroy", arena_pointer)
        invoke("pyjs.gc.destroy", heap_pointer)
