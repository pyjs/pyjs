"""Copied scalar bits do not retain objects; real copied references still do."""

import ctypes
import html
import struct

import pytest

from pyjs.native.runtime import collector, heap, roots
from pyjs.native.runtime.pointers import Pointer
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,argument,mutation", [
    ("list[int]", lambda bits: [bits], "pass"),
    ("list[int]", lambda bits: [bits], "value.extend([value[0]] * 20)"),
    ("list[int | None]", lambda bits: [bits, None], "pass"),
    ("list[int64]", lambda bits: [bits], "for index in range(20):\n        value.append(value[0])"),
    ("list[float]", lambda bits: [struct.unpack("d", struct.pack("Q", bits))[0]], "pass"),
    ("dict[int, int]", lambda bits: {bits: bits}, "pass"),
    ("dict[str, int]", lambda bits: {"kept": bits},
     "for index in range(20):\n        value[str(index)] = value['kept']"),
    ("dict[int, str]", lambda bits: {bits: "kept"},
     "for index in range(20):\n        value[-index - 1] = 'kept'"),
    ("set[int]", lambda bits: {bits}, "value.update(range(-20, 0))"),
    ("bytes", lambda bits: bits.to_bytes(8, "little"), "pass"),
    ("Holder", lambda bits: {"bits": bits}, "pass"),
    ("tuple[int, str]", lambda bits: (bits, "kept"), "pass"),
], ids=["list", "list-growth", "optional", "wide-growth", "float", "dict",
        "value-growth", "key-growth", "set-growth", "bytes", "record", "tuple"])
def test_copied_scalar_lanes_do_not_retain_unrelated_objects(tmp_path, optimize, annotation, argument, mutation):
    library = LLVM().compile_library(f'''
from pyjs import int64, llvm
from pyjs.native import gc_collect, gc_pin

class Box:
    def __init__(self):
        self.value = 42

class Holder:
    def __init__(self, bits: int):
        self.bits = bits

@llvm.inline("ptrtoint ptr {{value}} to i64")
def address(value: Box) -> int:
    return id(value)

def render(value: {annotation}, seed: bool) -> str:
    if seed:
        child = Box()
        gc_pin(child)
        return str(address(child))
    {mutation}
    gc_pin(value)
    gc_collect()
    return "done"
''', tmp_path, entry_point="render", optimize=optimize)
    state = heap._Heap.from_address(library._heap)
    owner = Pointer(library._heap)
    invoke = runtime_functions({"pyjs.gc.unpin": roots.unpin,
                                "pyjs.gc.try.collect": collector.try_collect}, library._library)
    try:
        counts = []
        for alias in (False, True):
            address = int(library.render(argument(0), True))
            invoke("pyjs.gc.unpin", owner, Pointer(address))
            assert library.render(argument(address if alias else 0), False) == "done"
            # Compare identical shapes, not a hard-coded allocation strategy:
            # adding an address to a scalar lane cannot keep its old owner alive.
            counts.append(state.count)
            pinned = roots._Pin.from_address(state.pins).value
            invoke("pyjs.gc.unpin", owner, Pointer(pinned))
            assert invoke("pyjs.gc.try.collect", owner) and state.count == 0
        assert counts[0] > 0 and counts[1] == counts[0], counts
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("value", ["", "snow 雪", b"", b"\x00\xff"])
def test_copied_text_owns_one_allocation_including_empty_values(tmp_path, optimize, value):
    from pyjs.tooling.llvm import _LLVMString

    annotation = "str" if isinstance(value, str) else "bytes"
    library = LLVM().compile_library(f'''
from pyjs.native import gc_collect, gc_pin
def render(value: {annotation}) -> str:
    gc_pin(value)
    gc_collect()
    return str(len(value))
''', tmp_path, entry_point="render", optimize=optimize)
    owner = Pointer(library._heap)
    state = heap._Heap.from_address(library._heap)
    invoke = runtime_functions({"pyjs.gc.unpin": roots.unpin,
                                "pyjs.gc.try.collect": collector.try_collect,
                                "pyjs.gc.find": collector.find}, library._library)
    try:
        assert library.render(value) == str(len(value))
        address = roots._Pin.from_address(state.pins).value
        assert invoke("pyjs.gc.try.collect", owner)
        assert state.count == 1
        text = _LLVMString.from_address(address)
        data = value.encode() if isinstance(value, str) else value
        assert text.length == len(data)
        assert text.data == address + ctypes.sizeof(_LLVMString)
        if data:
            assert ctypes.string_at(text.data, text.length) == data
        else:
            assert invoke("pyjs.gc.find", owner, Pointer(text.data)).address == 0
        invoke("pyjs.gc.unpin", owner, Pointer(address))
        assert invoke("pyjs.gc.try.collect", owner) and state.count == 0
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("direct", [False, True])
def test_copied_tagged_and_nested_graphs_survive_mutation_and_collection(tmp_path, optimize, direct):
    source = '''
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold

class Record:
    def __init__(self, label: str, small: int8, mixed: str | int, children: list[str]):
        self.label = label
        self.small = small
        self.mixed = mixed
        self.children = children

def render(value: Record, same: list[str], mapping: dict[int, list[str] | str]) -> str:
    gc_set_threshold(1)
    same.extend(['created' + str(index) for index in range(20)])
    for index in range(20):
        mapping[index] = same if index % 2 else 'label' + str(index)
    gc_collect()
    return repr((value.label, value.small, value.mixed, value.children is same,
                 value.children, mapping[19] is same, mapping[18]))
'''
    if direct:
        # Direct libraries take the output descriptor last and return its status.
        # They share promotion with buffered libraries, not their output path.
        source = "from pyjs.web.domx import div\nfrom pyjs.web.ssr import write_html_fd\n" + source
        source = source.replace("mapping: dict[int, list[str] | str]) -> str:",
                                "mapping: dict[int, list[str] | str], descriptor: int) -> int:")
        source = source.replace("    return repr(", "    result = repr(")
        source += "\n    return write_html_fd(div(result), descriptor)\n"
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize, direct=direct)
    try:
        for mixed in (42, "tagged"):
            shared = ["original"]
            record = {"label": "kept", "small": 7, "mixed": mixed, "children": shared}
            mapping = {1: shared, 2: "text"}
            expected = repr((
                "kept", 7, mixed, True, ["original", *[f"created{index}" for index in range(20)]],
                True, "label18"))
            if direct:
                expected = "<div>" + html.escape(expected, quote=False) + "</div>"
            assert library.render(record, shared, mapping) == expected
            assert shared == ["original"] and mapping == {1: shared, 2: "text"}
    finally:
        library.close()
