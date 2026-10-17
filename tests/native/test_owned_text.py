import ctypes
import subprocess
import sys
import textwrap

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime.pointers import Pointer, null
from pyjs.native.runtime.text_operations import concat_owned, new_owned
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import (
    String,
    runtime_functions,
    runtime_library,
    string,
)


def source():
    return transpile_llvm('def main() -> str: return ""')


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def owned_text(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, source)
    return runtime_functions({"pyjs.string.new.owned": new_owned,
                              "pyjs.string.concat.owned": concat_owned}, library)


def test_owned_text_allocates_header_and_payload_together_with_explicit_context(owned_text):
    buffers = []
    sizes = []

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        assert context == 123
        sizes.append(size)
        buffers.append(ctypes.create_string_buffer(b"!" * size))
        return ctypes.addressof(buffers[-1])

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    arguments = null(), allocator, Pointer(123)
    empty = owned_text("pyjs.string.new.owned", *arguments, 0)
    header = String.from_address(empty.address)
    assert header.length == 0 and header.data == empty.address + ctypes.sizeof(String)
    assert sizes == [ctypes.sizeof(String)]

    for left, right in ((b"", b""), (b"left", b""), ("é\0".encode(), "🙂".encode())):
        first, second = string(left), string(right)
        previous = len(sizes)
        result = owned_text("pyjs.string.concat.owned", *arguments,
                            Pointer(ctypes.addressof(first)), Pointer(ctypes.addressof(second)))
        header = String.from_address(result.address)
        assert header.length == len(left + right)
        assert ctypes.string_at(header.data, header.length) == left + right
        assert sizes[-1] == ctypes.sizeof(String) + len(left + right)
        assert header.data == result.address + ctypes.sizeof(String)
        assert len(sizes) == previous + 1
        assert buffers[-1].raw[-1:] == b"\0"


@pytest.mark.parametrize("optimize", [0, 2])
def test_foreign_text_owner_is_not_treated_as_a_heap_in_gc_code(tmp_path, optimize):
    ir = transpile_llvm('''
from pyjs.native import gc_collect
def main() -> str:
    gc_collect()
    return ""
''')
    library = ctypes.CDLL(str(LLVM().compile(ir, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions({"pyjs.string.new.owned": new_owned,
                                "pyjs.string.concat.owned": concat_owned}, library)
    # Reuse the exact coallocation/context checks with managed owner selection
    # linked in. The foreign context is deliberately not a valid heap pointer.
    test_owned_text_allocates_header_and_payload_together_with_explicit_context(invoke)


@pytest.mark.parametrize("optimize", [0, 2])
def test_owned_text_returns_null_before_invalid_writes_and_overflow(tmp_path, optimize):
    library = LLVM().compile(source(), tmp_path, shared=True, optimize=optimize)
    for mode, expected in (("allocation", "24\n"), ("negative", ""),
                           ("size-overflow", ""), ("overflow", "")):
        # Keep invalid-pointer probes in a child so an accidental dereference
        # cannot terminate pytest. Observe real allocator calls rather than IR.
        result = subprocess.run([sys.executable, "-c", textwrap.dedent(f'''
            import ctypes
            import resource

            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            library = ctypes.CDLL({str(library)!r})
            class String(ctypes.Structure):
                _fields_ = [("length", ctypes.c_int64), ("data", ctypes.c_void_p)]
            @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
            def allocate(context, size):
                print(size, flush=True)
                return None
            if {mode!r} == "overflow":
                function = getattr(library, "pyjs.string.concat.owned")
                function.argtypes = [ctypes.c_void_p] * 5
                first, second = String(9223372036854775807, None), String(1, None)
                arguments = ctypes.byref(first), ctypes.byref(second)
            else:
                function = getattr(library, "pyjs.string.new.owned")
                function.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_int64]
                arguments = (-1 if {mode!r} == "negative" else
                             9223372036854775807 if {mode!r} == "size-overflow" else 8,)
            function.restype = ctypes.c_void_p
            assert function(None, ctypes.cast(allocate, ctypes.c_void_p), None, *arguments) is None
        ''')], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout == expected
