"""Owned native-library lifecycle and Python/POSIX descriptor boundaries."""

import ctypes
import threading
from collections.abc import Mapping

import pytest

from pyjs.tooling.llvm import LLVM, LLVMLibrary, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("direct", [False, True])
def test_descriptor_conversion_never_truncates_to_another_open_file(tmp_path, optimize, direct):
    source = '''
        from pyjs.web.domx import div
        from pyjs.web.ssr import write_html_fd

        def main(descriptor: int) -> int:
            return write_html_fd(div("safe"), descriptor)
    ''' if direct else '''
        def main() -> str:
            return "<div>safe</div>"
    '''
    library = LLVM().compile_library(source, tmp_path, direct=direct, optimize=optimize)
    try:
        with (tmp_path / "destination").open("w+b") as destination:
            fd = destination.fileno()
            for value in (fd + 2**32, fd - 2**32, 2**31, -(2**31) - 1, 2**80, -(2**80)):
                with pytest.raises(OverflowError, match="Python int too large to convert to C int"):
                    library.render_to_fd(value)
            for value in (1.0, "1", None):
                with pytest.raises(TypeError):
                    library.render_to_fd(value)
            assert destination.tell() == 0
            assert library.render_to_fd(-1) == 9

            class Descriptor:
                calls = 0

                def __index__(self):
                    self.calls += 1
                    return fd

            indexed = Descriptor()
            assert library.render_to_fd(indexed) == 0
            assert indexed.calls == 1
            destination.seek(0)
            assert destination.read() == b"<div>safe</div>"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("document", [False, True])
def test_computed_descriptor_overflow_is_catchable_and_retryable(tmp_path, optimize, document):
    setup = "document = Document()" if document else "pass"
    call = 'document.write(div(document, "safe"), descriptor + offset)' if document else 'write_html_fd(div("safe"), descriptor + offset)'
    imports = "from pyjs.native import Document, div" if document else "from pyjs.web.domx import div\nfrom pyjs.web.ssr import write_html_fd"
    source = f'''{imports}
def main(offset: int, recover: bool, descriptor: int) -> int:
    {setup}
    try:
        return {call}
    except OverflowError:
        if recover:
            return 42
        raise
'''
    python = {}
    exec(source, python)
    library = LLVM().compile_library(source, tmp_path, direct=True, optimize=optimize)
    try:
        with (tmp_path / "destination").open("w+b") as destination:
            for offset in (2**32, -(2**32)):
                with pytest.raises(OverflowError) as expected:
                    python["main"](offset, False, destination.fileno())
                with pytest.raises(LLVMRuntimeError, match="Python int too large to convert to C int") as caught:
                    library.render_to_fd(destination.fileno(), offset, False)
                assert str(caught.value) == str(expected.value)
                assert caught.value.exception_type == "OverflowError"
                assert caught.value.exception_module == "builtins"
                assert library.render_to_fd(destination.fileno(), offset, True) == python["main"](
                    offset, True, destination.fileno(),
                ) == 42
            assert destination.tell() == 0
            assert library.render_to_fd(destination.fileno(), 0, False) == 0
            destination.seek(0)
            assert destination.read() == b"<div>safe</div>"
    finally:
        library.close()


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("close_during", ["before", "descriptor", "input", "other_thread"])
def test_closed_library_rejects_before_native_entry_and_after_host_callbacks(tmp_path, managed, close_during):
    setup = "gc_collect()" if managed else "pass"
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect

        class Box:
            def __init__(self, value: str):
                self.value = value

        def main(box: Box) -> str:
            {setup}
            return box.value
    ''', tmp_path)
    assert library.managed is managed
    callbacks = []
    converting, closed = threading.Event(), threading.Event()

    class Descriptor:
        def __index__(self):
            callbacks.append("descriptor")
            if close_during == "descriptor":
                library.close()
            return destination.fileno()

    class Box:
        @property
        def value(self):
            callbacks.append("input")
            if close_during == "input":
                library.close()
            if close_during == "other_thread":
                converting.set()
                assert closed.wait(10), "close blocked behind host conversion"
            return "must not write"

    def close_from_thread():
        if converting.wait(10):
            library.close()
            closed.set()

    thread = threading.Thread(target=close_from_thread) if close_during == "other_thread" else None
    try:
        if close_during == "before":
            library.close()
        if thread:
            thread.start()
        with (tmp_path / "destination").open("w+b") as destination:
            with pytest.raises(RuntimeError, match="native LLVM library is closed"):
                library.render_to_fd(Descriptor(), Box())
            assert destination.tell() == 0
        if close_during == "before":
            assert callbacks == []
        library.close()
        with pytest.raises(RuntimeError, match="native LLVM library is closed"):
            library.render_to_fd(0, Box())
        assert library._heap is None
    finally:
        converting.set()
        if thread:
            thread.join(10)
            assert not thread.is_alive()
        library.close()


@pytest.mark.parametrize("missing", [None, "pyjs_gc_delete", "pyjs_render_host_to_fd"])
def test_library_validates_exports_before_requesting_a_heap(tmp_path, missing):
    # This ABI fixture returns a supported allocation failure, never an invalid
    # heap pointer. Missing exports must reject before even requesting ownership.
    source = '''
        @calls = global i64 0
        define ptr @pyjs_gc_new() {
            %old = load i64, ptr @calls
            %next = add i64 %old, 1
            store i64 %next, ptr @calls
            ret ptr null
        }
        define void @pyjs_gc_delete(ptr %heap) { ret void }
        define i32 @pyjs_render_host_to_fd(ptr %heap, i32 %fd) { ret i32 0 }
        define i64 @heap_calls() {
            %n = load i64, ptr @calls
            ret i64 %n
        }
    '''
    if missing is not None:
        source = source.replace(f"@{missing}", f"@unavailable_{missing}")
    path = LLVM().compile(source, tmp_path, shared=True)
    raw = ctypes.CDLL(str(path))
    raw.heap_calls.restype = ctypes.c_int64
    for attempt in range(2):
        if missing is None:
            with pytest.raises(MemoryError, match="managed heap allocation failed"):
                LLVMLibrary(path, "", (), False, True, False, ())
            assert raw.heap_calls() == attempt + 1
        else:
            with pytest.raises(AttributeError, match=missing):
                LLVMLibrary(path, "", (), False, True, False, ())
            assert raw.heap_calls() == 0


@pytest.mark.parametrize("managed", [False, True])
def test_socket_wrapper_checks_closure_before_and_after_fileno(tmp_path, managed):
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect

        def main() -> str:
            {"gc_collect()" if managed else "pass"}
            return "must not write"
    ''', tmp_path)
    events = []

    class Destination:
        def fileno(self):
            events.append("fileno")
            library.close()
            return destination.fileno()

    try:
        with (tmp_path / "destination").open("w+b") as destination:
            with pytest.raises(RuntimeError, match="native LLVM library is closed"):
                library.render_to_socket(Destination())
            assert events == ["fileno"]
            events.clear()
            with pytest.raises(RuntimeError, match="native LLVM library is closed"):
                library.render_to_socket(Destination())
            assert events == []
            assert destination.tell() == 0
    finally:
        library.close()


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("action", ["value", "close", "raise", "nested"])
def test_float_conversion_hooks_finish_before_taking_the_native_lock(tmp_path, managed, action):
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect

        def main(value: float) -> str:
            {"gc_collect()" if managed else "pass"}
            return str(value)
    ''', tmp_path)
    events = []

    class Number(int):
        def __float__(self):
            # Fail instead of hanging if a future regression defers this hook
            # to ctypes argument conversion inside the locked native call.
            assert not library._lock.locked()
            events.append("float")
            if action == "close":
                library.close()
            if action == "raise":
                raise ValueError("conversion failed")
            if action == "nested":
                assert library.render(4.0) == "4.0"
            return 2.5

    try:
        with (tmp_path / "destination").open("w+b") as destination:
            if action in {"close", "raise"}:
                error, message = ((RuntimeError, "native LLVM library is closed") if action == "close"
                                  else (ValueError, "conversion failed"))
                with pytest.raises(error, match=message):
                    library.render_to_fd(destination.fileno(), Number(7))
                assert destination.tell() == 0
            else:
                assert library.render_to_fd(destination.fileno(), Number(7)) == 0
                destination.seek(0)
                assert destination.read() == b"2.5"
        assert events == ["float"]
        if action != "close":
            assert library.render(3.0) == "3.0"
        assert library._errors == []
    finally:
        library.close()


def test_record_marshalling_preserves_nested_read_order_and_failure_recovery(tmp_path):
    library = LLVM().compile_library('''
        from dataclasses import dataclass

        @dataclass
        class Child:
            value: str

        @dataclass
        class Row:
            child: Child
            suffix: str

        def render(row: Row) -> str:
            return row.child.value + row.suffix
    ''', tmp_path, entry_point="render")
    events = []

    class Record:
        def __init__(self, values):
            self.values = values

        def __getattr__(self, name):
            events.append(name)
            return self.values[name]

    class RecordMap(Mapping):
        def __init__(self, values):
            self.values = values

        def __getitem__(self, name):
            events.append(name)
            return self.values[name]

        def __iter__(self):
            return iter(self.values)

        def __len__(self):
            return len(self.values)

    try:
        for record_type in (Record, RecordMap):
            child = record_type({"value": "first"})
            row = record_type({"child": child, "suffix": "last"})
            events.clear()
            assert library.render(row) == "firstlast"
            assert events == ["child", "value", "suffix"]
            child.values["value"] = object()
            events.clear()
            with pytest.raises(TypeError, match="row.child.value must be str"):
                library.render(row)
            assert events == ["child", "value"]
            child.values["value"] = "retry"
            events.clear()
            assert library.render(row) == "retrylast"
            assert events == ["child", "value", "suffix"]
    finally:
        library.close()
