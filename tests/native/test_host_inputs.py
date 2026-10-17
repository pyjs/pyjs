"""Concrete copy-in ABI identity and collection shape contracts."""

import ctypes

import pytest

from pyjs.native.llvm import transpile_llvm_module
from pyjs.native.runtime import collector, heap, roots
from pyjs.tooling.llvm import LLVM, LLVMLibrary, LLVMRuntimeError
from tests.native.allocation_support import _fail_allocations
from tests.native.host_identity_fixtures import Record
from tests.native.runtime_support import runtime_functions


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_aliases_share_one_call_scoped_native_view(tmp_path, optimize):
    library = LLVM().compile_library('''
        def render(left: list[str], right: list[str], nested: tuple[list[str], str]) -> str:
            left.append("native")
            return str((left is right, left is nested[0], right, nested[1] is right[0]))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        for label in ("first", "second"):
            shared = [label]
            assert library.render(shared, shared, (shared, label)) == repr((True, True, [label, "native"], True))
            assert shared == [label]
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_mutated_host_graph_is_traced_and_call_scoped(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: str):
                self.value = value

        def change(values: dict[str, list[Box]], shared: list[Box]) -> None:
            shared.append(Box("created" + str(42)))
            values["new"] = shared

        def render(values: dict[str, list[Box]], shared: list[Box]) -> str:
            gc_set_threshold(1)
            change(values, shared)
            gc_collect()
            return str((values["old"] is values["new"], shared is values["new"], values["new"][1].value))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        for _ in range(3):
            shared = [{"value": "original"}]
            values = {"old": shared}
            assert library.render(values, shared) == "(True, True, 'created42')"
            assert values == {"old": [{"value": "original"}]}
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_concrete_nested_optional_and_numeric_mapping_inputs(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs import int8, float32
        from pyjs.native import gc_collect

        def render(values: dict[int8, tuple[float32, list[str] | None]], members: set[int8]) -> str:
            gc_collect()
            return str((values, sorted(members)))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render({1: (1.0, None), 257: (1.25, ["é"]), -1: (2.0, [])}, {1, 257, -1}) == "({1: (1.25, ['é']), -1: (2.0, [])}, [-1, 1])"
        assert library.render({}, set()) == "({}, [])"
        with pytest.raises(TypeError, match="must be str"):
            library.render({1: (1.0, [4])}, set())
        assert library.render({1: (1.0, None)}, set()) == "({1: (1.0, None)}, [])"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("shape", ["plain", "tagged", "headed", "hash-keys", "application-union"])
def test_promotion_failures_unwind_before_body_and_recover(tmp_path, optimize, raw, shape):
    annotation = {"plain": "dict[str, list[str]]", "tagged": "dict[str, list[str | int]] | int",
                  "hash-keys": "dict[str | int, list[str]]",
                  "headed": "dict[str, list[Record]]",
                  "application-union": "dict[str, list[Record | str]]"}[shape]
    narrowing = "if isinstance(value, int):\n                return str(value)" if shape == "tagged" else "pass"
    application = shape in {"headed", "application-union"}
    result = 'read(value["first"][0])' if application else 'str(value["first"][0])'
    module = transpile_llvm_module(f'''
        from pyjs import llvm
        from pyjs.native import gc_collect, gc_pin, gc_unpin
        from tests.native.host_identity_fixtures import Record

        def read(value: object) -> str:
            if isinstance(value, Record):
                return value.text
            return 'wrong identity'

        @llvm.inline("call void @test.entry()")
        def entered() -> None:
            pass

        def render(value: {annotation}) -> str:
            {narrowing}
            try:
                entered()
                gc_pin(value)
                gc_collect()
                result = {result}
                gc_unpin(value)
                return result
            except MemoryError:
                return "wrongly caught a prologue failure"
    ''', target="library", entry_point="render")
    ir = _fail_allocations(module.llvm_ir, True).replace(
        "@test.remaining = private global", "@test.remaining = global",
    ) + '''
        @test.entered = global i1 false
        define private void @test.entry() {
          store i1 true, ptr @test.entered
          store i64 0, ptr @test.remaining
          ret void
        }
    '''
    path = LLVM().compile(ir, tmp_path, shared=True, optimize=optimize)
    library = LLVMLibrary(path, ir, module.parameters, module.direct, module.managed,
                          module.exceptions, module.type_definitions)
    if raw:
        entry = library._library.pyjs_render_to_fd
        entry.argtypes, entry.restype = library._render.argtypes, library._render.restype
        library._render = entry
    remaining = ctypes.c_int64.in_dll(library._library, "test.remaining")
    entered = ctypes.c_bool.in_dll(library._library, "test.entered")
    state = heap._Heap.from_address(library._heap)
    try:
        for fail_at in range(1, 128):
            shared = [Record("retained")] if application else ["retained"]
            arguments = {"first": shared, "second": shared}
            remaining.value, entered.value = fail_at, False
            try:
                assert library.render(arguments) == "retained"
            except LLVMRuntimeError as error:
                assert error.exception_type == "MemoryError"
                assert not entered.value
                assert state.roots is None and state.index is None
                remaining.value = 0
                assert library.render(arguments) == "retained"
                assert state.roots is None and state.pins is None and state.index is None
            else:
                assert entered.value and fail_at > 8
                break
        else:
            pytest.fail("did not exhaust promotion allocation failure points")
    finally:
        remaining.value = 0
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_pinned_input_outlives_host_view(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_pin

        def render(value: list[str]) -> str:
            gc_pin(value)
            return value[0]
    ''', tmp_path, entry_point="render", optimize=optimize)
    invoke = runtime_functions({"pyjs.gc.try.collect": collector.try_collect,
                                "pyjs.gc.unpin": roots.unpin}, library._library)
    state = heap._Heap.from_address(library._heap)
    from pyjs.native.runtime.pointers import Pointer
    from pyjs.tooling.llvm import _LLVMList, _LLVMString

    try:
        assert library.render(["retained 雪"]) == "retained 雪"
        pin = roots._Pin.from_address(state.pins)
        retained = pin.value
        assert invoke("pyjs.gc.try.collect", Pointer(library._heap))
        value = _LLVMList.from_address(retained)
        text = _LLVMString.from_address(ctypes.c_void_p.from_address(value.data).value)
        assert ctypes.string_at(text.data, text.length).decode() == "retained 雪"
        invoke("pyjs.gc.unpin", Pointer(library._heap), Pointer(retained))
        assert invoke("pyjs.gc.try.collect", Pointer(library._heap))
        assert state.count == 0
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_scalar_storage_and_recursive_native_entry(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs import float32, int8
        from pyjs.native import gc_collect

        def render(values: list[tuple[float32 | None, int8 | None]], depth: int) -> str:
            if depth:
                render(values, depth - 1)
                gc_collect()
            else:
                values.append((float32(1.25), int8(3)))
            return str(values)
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        value = [(None, None), (0.5, 257)]
        assert library.render(value, 3) == "[(None, None), (0.5, 1), (1.25, 3)]"
        assert value == [(None, None), (0.5, 257)]
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("nested_tuple", [False, True])
def test_host_boundary_copy_growth_and_collection_under_asan(tmp_path, optimize, nested_tuple):
    annotation = "tuple[list[str], str]" if nested_tuple else "list[str]"
    sequence = "values[0]" if nested_tuple else "values"
    module = transpile_llvm_module(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        def render(values: {annotation}) -> str:
            gc_set_threshold(1)
            {sequence}.append("new" + str(42))
            gc_collect()
            return str(values)
    ''', target="library", entry_point="render")
    # Foreign storage has spare capacity. Promotion copies initialized entries
    # only, so the new header must not promise that original spare capacity.
    source = module.llvm_ir + '''
        @test.text = private constant [4 x i8] c"seed"
        @test.string = private constant %pyjs.string { i64 4, ptr @test.text }
        @test.data = private constant [8 x ptr] [ptr @test.string, ptr null,
          ptr null, ptr null, ptr null, ptr null, ptr null, ptr null]
        @test.source = private constant %pyjs.list { i64 1, i64 8,
          ptr @test.data, ptr null, ptr null, i64 0 }
        define private void @test.error(ptr %trace, ptr %message, ptr %type) {
          ret void
        }
        define i32 @main() {
          %heap = call ptr @pyjs_gc_new()
          %status = call i32 @pyjs_render_to_fd(ptr %heap, i32 1,
            ptr @test.error, ptr @test.source)
          call void @pyjs_gc_delete(ptr %heap)
          ret i32 %status
        }
    '''
    if nested_tuple:
        # Fixed tuples have the same header, pointing to a heterogeneous
        # payload; they do not pass that payload directly as the root pointer.
        source = source.replace("@test.source = private constant", "@test.list = private constant") + '''
            @test.tuple.data = private constant { ptr, ptr } { ptr @test.list, ptr @test.string }
            @test.source = private constant %pyjs.list { i64 2, i64 2,
              ptr @test.tuple.data, ptr null, ptr null, i64 0 }
        '''
    execution = LLVM()._run_ir(source, tmp_path, name="input-copy", optimize=optimize,
                               pass_fds=(), sanitizers=("address", "undefined"), timeout=10, artifacts=tmp_path)
    assert execution.returncode == 0, execution.stderr
    expected = "(['seed', 'new42'], 'seed')" if nested_tuple else "['seed', 'new42']"
    assert execution.stdout == expected
    assert execution.stderr == ""


@pytest.mark.parametrize("annotation,value", [
    ("str", ""), ("bytes", b""), ("tuple[()]", ()),
    ("list[int]", []), ("dict[str, str]", {}), ("set[str]", set()),
])
def test_empty_host_values_have_pinnable_identity(tmp_path, annotation, value):
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect, gc_pin, gc_unpin
        def render(value: {annotation}) -> str:
            gc_pin(value)
            gc_collect()
            gc_unpin(value)
            return str(len(value))
    ''', tmp_path, entry_point="render")
    try:
        assert library.render(value) == "0"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_grown_pinned_host_mapping_owns_both_buffers_after_call(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_pin

        def render(values: dict[int, str]) -> str:
            for index in range(1, 20):
                values[index] = "created" + str(index)
            gc_collect()
            gc_pin(values)
            return values[19]
    ''', tmp_path, entry_point="render", optimize=optimize)
    invoke = runtime_functions({"pyjs.gc.try.collect": collector.try_collect,
                                "pyjs.gc.find": collector.find,
                                "pyjs.gc.unpin": roots.unpin}, library._library)
    from pyjs.native.runtime.mappings import _Dict
    from pyjs.native.runtime.pointers import Pointer
    from pyjs.tooling.llvm import _LLVMString

    state = heap._Heap.from_address(library._heap)
    pointer = Pointer(library._heap)
    try:
        original = {0: "borrowed"}
        assert library.render(original) == "created19"
        assert original == {0: "borrowed"}
        retained = roots._Pin.from_address(state.pins).value
        value = _Dict.from_address(retained)
        # Check ownership before dereferencing: a missing value callback would
        # leave an arena buffer dangling once render() returns.
        assert invoke("pyjs.gc.find", pointer, Pointer(value.keys)).address
        assert invoke("pyjs.gc.find", pointer, Pointer(value.values)).address
        assert invoke("pyjs.gc.try.collect", pointer)
        keys = (ctypes.c_int64 * value.length).from_address(value.keys)
        texts = (ctypes.c_void_p * value.length).from_address(value.values)
        actual = {}
        for key, address in zip(keys, texts, strict=True):
            text = _LLVMString.from_address(address)
            actual[key] = ctypes.string_at(text.data, text.length).decode()
        assert actual == {0: "borrowed", **{index: f"created{index}" for index in range(1, 20)}}
        invoke("pyjs.gc.unpin", pointer, Pointer(retained))
        assert invoke("pyjs.gc.try.collect", pointer) and state.count == 0
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_mapping_order_buffer_is_copied_under_asan(tmp_path, optimize):
    module = transpile_llvm_module('''
        from pyjs.native import gc_collect

        def render(values: dict[int, int]) -> str:
            values.pop(1)
            values[3] = 30
            gc_collect()
            return str(values)
    ''', target="library", entry_point="render")
    # A raw caller may have previously formatted and mutated this mapping.
    # Immutable foreign arrays expose writes through a missed borrowed pointer.
    source = module.llvm_ir + '''
        @test.keys = private constant [2 x i64] [i64 1, i64 2]
        @test.values = private constant [2 x i64] [i64 10, i64 20]
        @test.order = private constant [2 x i64] [i64 1, i64 9]
        @test.source = private constant %pyjs.dict { i64 2, i64 2,
          ptr @test.keys, ptr @test.values, ptr null, ptr null,
          ptr @test.order, i64 10, ptr null, ptr null }
        define private void @test.error(ptr %trace, ptr %message, ptr %type) {
          ret void
        }
        define i32 @main() {
          %heap = call ptr @pyjs_gc_new()
          %status = call i32 @pyjs_render_to_fd(ptr %heap, i32 1,
            ptr @test.error, ptr @test.source)
          call void @pyjs_gc_delete(ptr %heap)
          ret i32 %status
        }
    '''
    execution = LLVM()._run_ir(source, tmp_path, name="mapping-copy", optimize=optimize,
                               pass_fds=(), sanitizers=("address", "undefined"), timeout=10, artifacts=tmp_path)
    assert execution.returncode == 0, execution.stderr
    assert execution.stdout == "{2: 20, 3: 30}"
    assert execution.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_mapping_and_set_inputs(tmp_path, optimize):
    library = LLVM().compile_library('''
        from urllib.parse import urlencode

        def render(values: dict[str, str], members: set[str]) -> str:
            before = urlencode(values)
            values["new"] = "é & +"
            members.add("native")
            return before + "|" + urlencode(values) + "|" + str(sorted(members))
    ''', tmp_path, entry_point="render", optimize=optimize)
    from urllib.parse import urlencode

    values, members = {"query": "雪 🙂", "page": "1"}, {"caller"}
    expected = urlencode(values) + "|" + urlencode({**values, "new": "é & +"}) + "|" + str(["caller", "native"])
    try:
        assert library.render(values, members) == expected
        assert values == {"query": "雪 🙂", "page": "1"}
        assert members == {"caller"}
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_host_mapping_through_query_and_dom_rendering(tmp_path, optimize):
    comparison = LLVM().assert_library_matches_python('''
        from urllib.parse import urlencode
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import tag
        from pyjs.web.ssr import render_html

        def render(query: dict[str, str]) -> str:
            gc_set_threshold(1)
            encoded = urlencode(query)
            gc_collect()
            return render_html(tag("a", {"href": "/logs?" + encoded}, "View logs"))
    ''', {"q": "雪 & status=error", "page": "1"}, directory=tmp_path,
        entry_point="render", optimize=optimize)
    comparison.library.close()


@pytest.mark.parametrize("reverse", [False, True])
def test_input_memo_growth_and_root_order(tmp_path, reverse):
    parameters = "values: list[list[str]], shared: list[str]"
    if reverse:
        parameters = "shared: list[str], values: list[list[str]]"
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect

        SAVED: list[list[list[str]]] = []

        def render({parameters}) -> str:
            SAVED.append(values)
            shared[0] = "changed"
            gc_collect()
            count = 0
            for value in values:
                if value is shared:
                    count += 1
            return str((count, values[0][0], values[-1][0],
                        SAVED[0][1], SAVED[0][-2], len(SAVED)))
    ''', tmp_path, entry_point="render")
    shared = ["original"]
    # Grow the identity table with distinct headers between shared aliases.
    values = [shared, *[[str(index)] for index in range(512)], shared]
    try:
        for size, inputs in enumerate((values, [shared]), 1):
            arguments = (shared, inputs) if reverse else (inputs, shared)
            assert library.render(*arguments) == repr((3 - size, "changed", "changed", ["0"], ["511"], size))
            assert shared == ["original"]
    finally:
        library.close()


@pytest.mark.parametrize("annotation, value", [("str", "shared"), ("bytes", b"shared")])
def test_retained_immutable_input_headers_preserve_identity(tmp_path, annotation, value):
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect
        SAVED: list[{annotation}] = []

        def render(left: {annotation}, right: {annotation}) -> str:
            SAVED.append(left)
            gc_collect()
            return str((left is right, left is not right, SAVED))
    ''', tmp_path, entry_point="render")
    try:
        for count, right in enumerate((value, value, value + value), 1):
            assert library.render(value, right) == repr((value is right, value is not right, [value] * count))
    finally:
        library.close()


def test_retained_none_inputs_preserve_optional_first_root_and_validate_paths(tmp_path):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold
        SAVED: list[list[None]] = []

        def render(optional: list[None] | None, value: list[None],
                   empty: None, pair: tuple[None, list[None]]) -> str:
            gc_set_threshold(1)
            SAVED.append(value)
            gc_collect()
            return str((optional is value, empty, pair[0], pair[1] is value, SAVED))
    ''', tmp_path, entry_point="render")
    shared = [None]
    try:
        assert library.render(None, shared, None, (None, shared)) == repr((False, None, None, True, [[None]]))
        assert library.render(shared, shared, None, (None, shared)) == repr((True, None, None, True, [[None], [None]]))
        with pytest.raises(TypeError, match="empty must be None"):
            library.render(None, shared, 0, (None, shared))
        with pytest.raises(TypeError, match=r"value\[0\] must be None"):
            library.render(None, [0], None, (None, shared))
        assert library.render(None, shared, None, (None, shared)) == repr((False, None, None, True, [[None]] * 3))
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_retained_inplace_repetition_preserves_host_aliases(tmp_path, optimize, reverse):
    parameters = "left: list[str], right: list[str], nested: list[list[str]]"
    if reverse:
        parameters = "nested: list[list[str]], right: list[str], left: list[str]"
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        SAVED: list[list[str]] = []

        def render({parameters}, count: int) -> str:
            gc_set_threshold(1)
            SAVED.append(left)
            left *= count
            gc_collect()
            return str((left is right, left is nested[0], right, SAVED))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        expected = []
        for count in (3, 0, 1, 5):
            value = ["ship", "master"]
            expected.append(value * count)
            arguments = ([value], value, value) if reverse else (value, value, [value])
            assert library.render(*arguments, count) == repr((True, True, value * count, expected))
            assert value == ["ship", "master"]
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_borrowed_parent_preserves_already_managed_child_identity(tmp_path, optimize, reverse):
    parameters = "shared: list[int], nested: list[list[int]]" if reverse else "nested: list[list[int]], shared: list[int]"
    module = transpile_llvm_module(f'''
        from pyjs.native import gc_collect

        def render({parameters}) -> str:
            shared.append(99)
            gc_collect()
            return str((nested[0] is shared, nested[0], shared))
    ''', target="library", entry_point="render")
    arguments = "ptr %child, ptr %outer" if reverse else "ptr %outer, ptr %child"
    # The outer header/data are borrowed stack storage. Its child is already
    # managed, pinned and also passed directly: neither encounter may clone it.
    source = module.llvm_ir + '''
        define private void @test.error(ptr %trace, ptr %message, ptr %type) { ret void }
        define i32 @main() {
          %heap = call ptr @pyjs_gc_new()
          %child.size = ptrtoint ptr getelementptr (%pyjs.list, ptr null, i32 1) to i64
          %child = call ptr @pyjs.gc.try.alloc.described(ptr %heap, i64 %child.size, ptr null)
          %data = call ptr @pyjs.gc.try.alloc.described(ptr %heap, i64 8, ptr null)
          store i64 7, ptr %data
          %c0 = insertvalue %pyjs.list zeroinitializer, i64 1, 0
          %c1 = insertvalue %pyjs.list %c0, i64 1, 1
          %c2 = insertvalue %pyjs.list %c1, ptr %data, 2
          %c3 = insertvalue %pyjs.list %c2, ptr @pyjs.gc.alloc.adapter, 3
          %c4 = insertvalue %pyjs.list %c3, ptr %heap, 4
          store %pyjs.list %c4, ptr %child
          %pinned = call i1 @pyjs.gc.try.pin(ptr %heap, ptr %child)
          %nested_data = alloca ptr
          store ptr %child, ptr %nested_data
          %outer = alloca %pyjs.list
          %o0 = insertvalue %pyjs.list zeroinitializer, i64 1, 0
          %o1 = insertvalue %pyjs.list %o0, i64 1, 1
          %o2 = insertvalue %pyjs.list %o1, ptr %nested_data, 2
          store %pyjs.list %o2, ptr %outer
    ''' + f'''
          %status = call i32 @pyjs_render_to_fd(ptr %heap, i32 1, ptr @test.error, {arguments})
          call void @pyjs.gc.unpin(ptr %heap, ptr %child)
          call void @pyjs_gc_delete(ptr %heap)
          ret i32 %status
        }}
    '''
    execution = LLVM()._run_ir(source, tmp_path, name="mixed-ownership", optimize=optimize,
                               pass_fds=(), sanitizers=("address", "undefined"), timeout=10, artifacts=tmp_path)
    assert execution.returncode == 0, execution.stderr
    assert execution.stdout == "(True, [7, 99], [7, 99])"
    assert execution.stderr == ""


@pytest.mark.parametrize("raw", [False, True])
def test_input_copy_bounds_ownership_work_against_retained_heap(tmp_path, raw):
    module = transpile_llvm_module('''
        from pyjs.native import gc_pin, gc_set_threshold

        def render(count: int, values: list[str], label: str) -> str:
            gc_set_threshold(10000000)
            if count:
                retained: list[str] = []
                for index in range(count):
                    retained.append(str(index))
                gc_pin(retained)
            return values[0] + label
    ''', target="library", entry_point="render")
    # Count actual ownership work, not wall-clock timing. Python skips lookup;
    # raw calls use a stable indexed snapshot, never the growing copy heap.
    header = "define ptr @pyjs.gc.find(ptr %arg.heap, ptr %arg.candidate) {\nblock.entry:\n"
    assert module.llvm_ir.count(header) == 1
    ir = module.llvm_ir.replace(header, header + '''
        %test.count = load i64, ptr @test.find.calls
        %test.next = add i64 %test.count, 1
        store i64 %test.next, ptr @test.find.calls
        %test.index.slot = getelementptr %pyjs.gc, ptr %arg.heap, i32 0, i32 8
        %test.index = load ptr, ptr %test.index.slot
        %test.unindexed = icmp eq ptr %test.index, null
        %test.objects.slot = getelementptr %pyjs.gc, ptr %arg.heap, i32 0, i32 3
        %test.objects = load i64, ptr %test.objects.slot
        %test.linear = select i1 %test.unindexed, i64 %test.objects, i64 0
        %test.old.work = load i64, ptr @test.find.work
        %test.work = add i64 %test.old.work, %test.linear
        store i64 %test.work, ptr @test.find.work
        %test.old.objects = load i64, ptr @test.find.objects
        %test.total.objects = add i64 %test.old.objects, %test.objects
        store i64 %test.total.objects, ptr @test.find.objects
    ''') + "\n@test.find.calls = global i64 0\n@test.find.work = global i64 0\n@test.find.objects = global i64 0\n"
    entry_header = next(line for line in ir.splitlines() if line.startswith("define ptr @fn.pyjs_main(")) + "\nblock.entry:\n"
    assert ir.count(entry_header) == 1
    ir = ir.replace(entry_header, entry_header + '''
        %test.chunk = load ptr, ptr %arg.__arena
        store ptr %test.chunk, ptr @test.entry.chunk
    ''') + "\n@test.entry.chunk = global ptr null\n"
    path = LLVM().compile(ir, tmp_path, shared=True)
    library = LLVMLibrary(path, ir, module.parameters, module.direct, module.managed,
                          module.exceptions, module.type_definitions)
    count = ctypes.c_int64.in_dll(library._library, "test.find.calls")
    work = ctypes.c_int64.in_dll(library._library, "test.find.work")
    objects = ctypes.c_int64.in_dll(library._library, "test.find.objects")
    scratch = ctypes.c_void_p.in_dll(library._library, "test.entry.chunk")
    if raw:
        entry = library._library.pyjs_render_to_fd
        entry.argtypes, entry.restype = library._render.argtypes, library._render.restype
        library._render = entry
    try:
        # Immutable strings now co-allocate header and payload. Keep the same
        # large-heap workload instead of assuming two allocations per string.
        assert library.render(20000, ["first"], "!") == "first!"
        assert scratch.value is None
        assert heap._Heap.from_address(library._heap).count > 20000
        assert count.value > 0  # Pinning exercised the instrumented primitive.
        for length in (2, 100, 400):
            count.value = work.value = objects.value = 0
            before = heap._Heap.from_address(library._heap).count
            assert library.render(0, ["next"] * length, "!") == "next!"
            assert scratch.value is None
            assert work.value == 0
            assert count.value == (length + 2 if raw else 0)
            assert objects.value == before * count.value
    finally:
        library.close()
