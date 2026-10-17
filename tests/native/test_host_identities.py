"""Host snapshots acquire trusted native identities only during promotion."""

import pytest

from pyjs.native.llvm import transpile_llvm_module
from pyjs.tooling.llvm import LLVM
from tests.native.host_identity_fixtures import Empty, PackedRecord, Record, SpecialRecord
from tests.native.model_inputs_fixtures import Setting


@pytest.mark.parametrize("optimize", [0, 2])
def test_headed_records_preserve_aliases_and_virtual_dispatch(tmp_path, optimize):
    source = '''
from tests.native.host_identity_fixtures import Record, SpecialRecord, Empty
from pyjs.native import gc_collect, gc_set_threshold
def label(value: object) -> str:
    if isinstance(value, Record):
        return value.label()
    return 'empty' if isinstance(value, Empty) else 'wrong'
def render(value: Record, child: SpecialRecord, aliases: list[Record], empty: Empty, optional: Record | None) -> str:
    gc_set_threshold(1)
    gc_collect()
    return str((label(value), label(child), label(empty), value is aliases[0],
                value.items is aliases[0].items, value.items[0], child.items[0],
                optional is value, optional.text if optional is not None else 'absent'))
'''
    value, child, empty = Record('base'), SpecialRecord('child'), Empty()
    comparison = LLVM().assert_library_matches_python(source, value, child, [value], empty, value,
                                                       directory=tmp_path, entry_point="render", optimize=optimize)
    library = comparison.library
    try:
        assert library.managed
        for invalid in ({"text": "structural", "items": []}, child):
            with pytest.raises(TypeError, match="exact Record"):
                library.render(invalid, child, [value], empty, value)
            assert library.render(value, child, [value], empty, value) == comparison.python
        assert library.render(value, child, [value], empty, None).endswith("False, 'absent')")
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_headed_portable_fields_keep_native_alignment(tmp_path, optimize):
    comparison = LLVM().assert_library_matches_python('''
from typing import cast
from tests.native.host_identity_fixtures import PackedRecord
from pyjs.native import gc_collect
def read(value: object) -> PackedRecord:
    return cast(PackedRecord, value)
def render(value: PackedRecord) -> str:
    gc_collect()
    selected = read(value)
    return str((selected.tiny, selected.number, selected.ready, selected.text))
''', PackedRecord('é<&'), directory=tmp_path, entry_point="render", optimize=optimize)
    comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_identity_only_inputs_enable_promotion_without_user_gc_calls(tmp_path, optimize):
    library = LLVM().compile_library('''
from tests.native.host_identity_fixtures import SpecialRecord
def render(value: SpecialRecord) -> str:
    return value.text
''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.managed
        assert library.render(SpecialRecord('kept')) == 'kept'
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_dom_headers_do_not_change_model_snapshot_semantics(tmp_path, optimize):
    source = '''
from tests.native.model_inputs_fixtures import Setting
from pyjs.web.dom import Element
from pyjs.web.domx import div, span
from pyjs.web.ssr import render_html
from pyjs.native import gc_collect, gc_set_threshold
def panel(*items: object) -> Element:
    return div(*items)
def render(value: Setting, aliases: list[Setting]) -> str:
    gc_set_threshold(1)
    value.labels.append('native')
    gc_collect()
    return render_html(panel(value.name, span('|'.join(aliases[0].labels))))
'''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    value = Setting(name='a<&')
    try:
        for _ in range(2):
            assert library.render(value, [value]) == '<div>A&lt;&amp;<span>default|native</span></div>'
            assert value.labels == ['default']
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("entry", ["pyjs_render_to_fd", "pyjs_render_host_to_fd"])
def test_borrowed_record_header_is_replaced_before_dispatch_under_asan(tmp_path, optimize, entry):
    module = transpile_llvm_module('''
from tests.native.host_identity_fixtures import PackedRecord
from pyjs.native import gc_collect
def read(value: object) -> str:
    gc_collect()
    if isinstance(value, PackedRecord):
        return str((value.tiny, value.number, value.ready, value.text))
    return 'wrong identity'
def render(value: PackedRecord) -> str:
    return read(value)
''', target="library", entry_point="render")
    # A read-only borrowed snapshot has ABI-aligned scalar/reference fields and
    # a deliberately invalid header. Copy-in must overwrite only the native
    # copy before any runtime type query or collection.
    source = module.llvm_ir + '''
@test.text = private constant [4 x i8] c"safe"
@test.string = private constant %pyjs.string { i64 4, ptr @test.text }
@test.record = private constant { ptr, i8, float, i1, ptr } {
  ptr inttoptr (i64 2989 to ptr), i8 -3, float 1.25, i1 true, ptr @test.string }
define private void @test.error(ptr %trace, ptr %message, ptr %type) { ret void }
define i32 @main() {
  %heap = call ptr @pyjs_gc_new()
  %status = call i32 @ENTRY(ptr %heap, i32 1, ptr @test.error, ptr @test.record)
  call void @pyjs_gc_delete(ptr %heap)
  ret i32 %status
}
'''.replace('@ENTRY', '@' + entry)
    execution = LLVM()._run_ir(source, tmp_path, name="headed-input", optimize=optimize,
                               pass_fds=(), sanitizers=("address", "undefined"), timeout=10, artifacts=tmp_path)
    assert execution.returncode == 0, execution.stderr
    assert execution.stdout == repr((-3, 1.25, True, "safe"))
    assert execution.stderr == ""
