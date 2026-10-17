"""Pydantic copy-in is a field snapshot, not a compiled model implementation."""

import tempfile

import pytest

from pyjs import int8
from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm_module
from pyjs.server import Page
from pyjs.tooling.llvm import LLVM
from tests.native.model_inputs_fixtures import (
    Catalog,
    CatalogPage,
    ExtendedSetting,
    InheritedPageRecord,
    NumericSetting,
    PageRecord,
    Setting,
    UnionPages,
    calls,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_framework_generic_model_inputs_keep_exact_specializations(tmp_path, optimize):
    from pyjs.server.pagination import OffsetPageRequest

    library = LLVM().compile_library('''
        from __future__ import annotations
        from typing import Annotated
        from pyjs.server import Page
        from pyjs.server.pagination import OffsetPageRequest
        from pyjs.native import gc_collect
        type TextPage = Page[str]
        def render(page: Annotated[TextPage, {'host': True}], request: OffsetPageRequest) -> str:
            gc_collect()
            total = page.total
            return ','.join(page.items) + ':' + ('none' if total is None else str(total)) + ':' + str(request.page)
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        class Subpage(Page[str]):
            pass

        request = OffsetPageRequest(page=2)
        assert library.render(Page[str](items=['alpha', 'β'], total=2), request) == 'alpha,β:2:2'
        assert library.render(Page[str](items=[]), request) == ':none:2'
        for invalid in (Page[int](items=[1]), Page(items=['untyped']), Subpage(items=[])):
            with pytest.raises(TypeError, match=r'exact Page\[str\]'):
                library.render(invalid, request)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_generic_models_and_literal_fields_copy_under_gc(tmp_path, optimize):
    setting = Setting(name='nested')
    value = CatalogPage(page=Page[Setting](items=[setting, setting], total=2))
    before = calls.copy()
    comparison = LLVM().assert_library_matches_python('''
        from tests.native.model_inputs_fixtures import CatalogPage
        from pyjs.native import gc_collect, gc_set_threshold
        def render(value: CatalogPage) -> str:
            gc_set_threshold(1)
            gc_collect()
            page = value.page
            return str((value.status.upper(), page.items[0].name,
                        page.items[0] is page.items[1], page.total))
    ''', value, directory=tmp_path, entry_point="render", optimize=optimize)
    try:
        assert comparison.library.render(value) == "('READY', 'NESTED', True, 2)"
        assert calls == before
    finally:
        comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_filtered_model_inputs_preserve_nested_fields_and_host_identity(tmp_path, optimize):
    shared = Setting(name='alpha', size=2)
    value = Catalog(settings=[Setting(name='ignored'), shared, Setting(name='', size=3),
                              Setting(name='βeta', size=4)], featured=shared)
    before = calls.copy()
    comparison = LLVM().assert_library_matches_python('''
        from tests.native.model_inputs_fixtures import Catalog
        from pyjs.native import gc_collect, gc_set_threshold
        def render(value: Catalog) -> str:
            gc_set_threshold(1)
            selected = [item.name for item in value.settings if item.count > 1]
            labels = [name + '!' for name in selected if name]
            gc_collect()
            featured = value.featured
            return ','.join(labels) + ':' + (featured.name if featured is not None else 'none')
    ''', value, directory=tmp_path, entry_point="render", optimize=optimize)
    try:
        assert comparison.library.render(value) == 'ALPHA!,ΒETA!:ALPHA'
        assert value.featured is value.settings[1]
        assert calls == before
    finally:
        comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_models_in_optional_collection_inputs(tmp_path, optimize):
    source = '''
        from pyjs.server import Page
        from pyjs.native import gc_collect
        def render(values: dict[str, list[tuple[Page[str] | None, Page[str]]]]) -> str:
            first, second = values['pages'][0]
            gc_collect()
            return str((first is second, ','.join(second.items)))
    '''
    page = Page[str](items=['a', 'b'])
    comparison = LLVM().assert_library_matches_python(source, {'pages': [(page, page)]},
        directory=tmp_path, entry_point="render", optimize=optimize)
    try:
        assert comparison.library.render({'pages': [(None, page)]}) == "(False, 'a,b')"
        with pytest.raises(TypeError, match=r'exact Page\[str\]'):
            comparison.library.render({'pages': [(Page[int](items=[]), page)]})
    finally:
        comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("shape", ["direct", "aliased", "nullable_alias"])
def test_union_container_members_preserve_generic_host_identity(tmp_path, optimize, shape):
    declaration, annotation, absent = {
        "direct": ("", "int | list[Page[str]]", "int"),
        "aliased": ("type Items = list[Page[str]]\ntype Choice = Items | int", "Choice", "int"),
        "nullable_alias": ("type Missing = None\ntype Items = list[Page[str]]", "Missing | Items", "None"),
    }[shape]
    check = "value is None" if absent == "None" else "isinstance(value, int)"
    source = f'''
from pyjs.server import Page
from pyjs.native import gc_collect
{declaration}
def render(value: {annotation}) -> str:
    gc_collect()
    if {check}:
        return 'absent'
    return ','.join(value[0].items)
'''
    comparison = LLVM().assert_library_matches_python(source, [Page[str](items=['a', 'β'])],
        directory=tmp_path, entry_point="render", optimize=optimize)
    try:
        assert comparison.library.render(None if absent == "None" else 7) == 'absent'
        for invalid in (Page[int](items=[1]), Page(items=['untyped'])):
            with pytest.raises(TypeError, match='exact Page'):
                comparison.library.render([invalid])
        assert comparison.library.render([Page[str](items=['retry'])]) == 'retry'
    finally:
        comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("record", [PageRecord, InheritedPageRecord, UnionPages])
def test_record_fields_preserve_generic_model_specialization(tmp_path, optimize, record):
    is_union = record is UnionPages
    body = ("pages = value.pages\n    if isinstance(pages, int):\n        return str(pages)\n"
            "    page = pages[0]" if is_union else "page = value.page")
    source = f'''
from tests.native.model_inputs_fixtures import {record.__name__}
from pyjs.native import gc_collect, gc_set_threshold
def render(value: {record.__name__}) -> str:
    gc_set_threshold(1)
    gc_collect()
    {body}
    return ','.join(page.items)
'''
    page = Page[str](items=['a', 'β'])
    value = record(pages=[page]) if is_union else record(page)
    comparison = LLVM().assert_library_matches_python(source, value, directory=tmp_path,
        entry_point="render", optimize=optimize)
    try:
        for invalid in (Page[int](items=[1]), Page(items=['untyped'])):
            # Bypass host validation deliberately; native copy-in must still
            # check every nested nominal model without rerunning validators.
            bad = record.model_construct(pages=[invalid]) if is_union else record(invalid)
            with pytest.raises(TypeError, match=r'exact Page\[str\]'):
                comparison.library.render(bad)
        assert comparison.library.render(value) == 'a,β'
        if is_union:
            assert comparison.library.render(record(pages=7)) == '7'
    finally:
        comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_model_container_union_order_preserves_shared_host_views(tmp_path, optimize):
    source = '''
        from pyjs.server import Page
        from pyjs.native import gc_collect
        def render(first: int | list[Page[str]], second: list[Page[str]] | int) -> str:
            gc_collect()
            if isinstance(first, int) or isinstance(second, int):
                return 'scalar'
            return str((first is second, first[0] is second[0]))
    '''
    pages = [Page[str](items=['shared'])]
    comparison = LLVM().assert_library_matches_python(source, pages, pages, directory=tmp_path,
        entry_point="render", optimize=optimize)
    try:
        assert comparison.library.render(pages, pages) == '(True, True)'
        assert comparison.library.render(pages, pages.copy()) == '(False, True)'
    finally:
        comparison.library.close()


def test_inferred_generic_model_record_field_needs_nominal_annotation():
    with pytest.raises(LLVMUnsupported, match="declare the containing record field at class level") as caught:
        transpile_llvm_module('''
        from pyjs.server import Page
        class Holder:
            def __init__(self, page: Page[str]):
                self.page = page
        def render(value: Holder) -> str:
            return ','.join(value.page.items)
        ''', target="library", entry_point="render")
    assert caught.value.__notes__ == ['while preparing library input field Holder.page']


def test_nested_input_diagnostic_names_each_record_field():
    with pytest.raises(LLVMUnsupported, match="concrete host annotation") as caught:
        transpile_llvm_module('''
        from pyjs.server import Page
        class Holder:
            def __init__(self, page: Page[str]):
                self.page = page
        class Outer:
            def __init__(self, holders: list[Holder]):
                self.holders = holders
        def render(value: Outer) -> str:
            return ','.join(value.holders[0].page.items)
        ''', target="library", entry_point="render")
    assert caught.value.__notes__ == [
        'while preparing library input field Holder.page',
        'while preparing library input field Outer.holders',
    ]


@pytest.mark.parametrize("optimize", [0, 2])
def test_semantically_equal_generic_models_keep_distinct_host_identities(tmp_path, optimize):
    source = '''
        from pyjs.server import Page
        def render(first: Page[str | int] | None, second: Page[int | str] | None) -> str:
            if first is None or second is None:
                return 'missing'
            return str(first.items) + str(second.items)
    '''
    module = transpile_llvm_module(source, target='library', entry_point='render')
    first, second = [parameter.value_type.resolve(module.type_definitions).item_type
                     for parameter in module.parameters]
    assert first.host_model is Page[str | int]
    assert second.host_model is Page[int | str]
    assert first.host_model is not second.host_model
    first_value, second_value = Page[str | int](items=['a', 1]), Page[int | str](items=[2, 'b'])
    comparison = LLVM().assert_library_matches_python(source, first_value, second_value,
        directory=tmp_path, entry_point='render', optimize=optimize)
    try:
        assert comparison.library.render(None, None) == 'missing'
        for pair in ((second_value, second_value), (first_value, first_value)):
            with pytest.raises(TypeError, match='exact Page'):
                comparison.library.render(*pair)
    finally:
        comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_validated_model_fields_and_aliases_copy_without_validation(tmp_path, optimize):
    setting = Setting(name="hello", size=3, optional="é")
    catalog = Catalog(settings=[setting, setting], featured=setting)
    before = calls.copy()
    comparison = LLVM().assert_library_matches_python('''
        from tests.native.model_inputs_fixtures import Catalog
        from pyjs.native import gc_collect, gc_set_threshold
        def render(value: Catalog) -> str:
            gc_set_threshold(1)
            gc_collect()
            first = value.settings[0]
            return str((first.name, first.count, first.labels, first.optional,
                        first is value.settings[1], first is value.featured))
    ''', catalog, directory=tmp_path, entry_point="render", optimize=optimize)
    try:
        assert comparison.library.render(catalog) == "('HELLO', 3, ['default'], 'é', True, True)"
        assert calls == before
    finally:
        comparison.library.close()


def test_model_inputs_reject_structural_substitutes_and_copy_nested_mutation(tmp_path):
    library = LLVM().compile_library('''
        from tests.native.model_inputs_fixtures import Setting
        from pyjs.native import gc_collect
        def render(value: Setting) -> str:
            value.labels.append('native')
            gc_collect()
            return value.name + ':' + ','.join(value.labels)
    ''', tmp_path, entry_point="render")
    try:
        setting = Setting(name="good")
        for invalid in (setting.model_dump(), ExtendedSetting(name="sub")):
            with pytest.raises(TypeError, match="exact Setting"):
                library.render(invalid)
        malformed = Setting.model_construct(name=3, labels=[])
        with pytest.raises(TypeError, match="must be str"):
            library.render(malformed)
        for _ in range(2):
            assert library.render(setting) == "GOOD:default,native"
            assert setting.labels == ["default"]
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_model_inheritance_promotes_an_exact_host_record(tmp_path, optimize):
    comparison = LLVM().assert_library_matches_python('''
        from tests.native.model_inputs_fixtures import ExtendedSetting
        from pyjs.native import gc_collect
        def render(value: ExtendedSetting) -> str:
            gc_collect()
            return str((value.name, value.count, value.enabled))
        ''', ExtendedSetting(name="child"), directory=tmp_path, entry_point="render", optimize=optimize)
    comparison.library.close()


@pytest.mark.parametrize("body", [
    "value.name = 'changed'\n    return ''",
    "value.count += 1\n    return ''",
    "del value.name\n    return ''",
    "return str(value)",
    "return repr(value)",
    "return ascii(value)",
    "print(value)\n    return ''",
    "return f'{value}'",
    "return str(value == value)",
    "return str(hash(value))",
    "return str(value.__hash__())",
    "return str(bool(value))",
    "return 'yes' if value else 'no'",
    "return repr([value])",
    "return str([value])",
    "return repr({'model': (value,)})",
    "return Setting(name='new').name",
    "Setting.__init__(value, name='new')\n    return ''",
    "initializer = value.__init__\n    initializer(name='new')\n    return ''",
])
def test_model_operations_do_not_silently_use_object_semantics(body):
    source = '''
from tests.native.model_inputs_fixtures import Setting
def render(value: Setting) -> str:
    BODY
'''.replace("BODY", body)
    with pytest.raises(CompilationError, match="(Pydantic|read-only)"):
        transpile_llvm_module(source, target="library", entry_point="render")


def test_model_portable_field_representation_is_preserved(tmp_path):
    source = '''
from tests.native.model_inputs_fixtures import NumericSetting
def render(value: NumericSetting) -> str:
    return str(value.count + 1)
'''
    module = transpile_llvm_module(source, target="library", entry_point="render")
    assert module.parameters[0].value_type.fields[0].value_type.numeric_format.bits == 8
    library = LLVM().compile_library(source, tmp_path, entry_point="render")
    try:
        assert library.render(NumericSetting(count=int8(127))) == "-128"
    finally:
        library.close()


@pytest.mark.parametrize("expression", ["str(bool(value))", "'yes' if value else 'no'"])
def test_model_custom_truth_is_not_silently_erased(expression):
    with pytest.raises(CompilationError, match="Pydantic"):
        transpile_llvm_module(f'''
        from tests.native.model_inputs_fixtures import CustomTruth
        def render(value: CustomTruth) -> str:
            return {expression}
        ''', target="library", entry_point="render")


@pytest.mark.parametrize("operation", ["bool(value)", "repr(value)", "value == value"])
def test_headed_model_erasure_does_not_enable_host_protocols(operation):
    with pytest.raises(CompilationError, match="Pydantic"):
        transpile_llvm_module(f'''
        from tests.native.model_inputs_fixtures import CustomTruth
        def check(value: object) -> str:
            return str({operation})
        def render(value: CustomTruth) -> str:
            return check(value)
        ''', target="library", entry_point="render")


def test_incomplete_model_requires_explicit_host_rebuild():
    with pytest.raises(CompilationError, match="Rebuild Pydantic model Unready"):
        transpile_llvm_module('''
        from pydantic import BaseModel
        class Unready(BaseModel):
            child: "NotDefinedYet"
        def render(value: Unready) -> str:
            return 'unused'
        ''', target="library", entry_point="render")


@pytest.mark.parametrize("expression", [
    "value.label()", "value.size", "value.double", "value.model_dump()",
])
@pytest.mark.parametrize("annotation", ["View", "View | Other"])
def test_model_host_members_have_a_field_only_diagnostic(expression, annotation):
    with pytest.raises(CompilationError, match="Field-only library model.*host-side member"):
        transpile_llvm_module(f'''
        from pydantic import BaseModel, computed_field
        from pyjs import js
        @js
        class View(BaseModel):
            name: str
            def label(self) -> str:
                return self.name
            @property
            def size(self) -> int:
                raise RuntimeError('do not execute host descriptors')
            @computed_field
            @property
            def double(self) -> str:
                return self.name * 2
        class Other(BaseModel):
            name: str
        def render(value: {annotation}) -> str:
            return str({expression})
        ''', target="library", entry_point="render")


def test_model_missing_members_keep_the_ordinary_attribute_diagnostic():
    with pytest.raises(CompilationError, match="Attribute 'absent'.*not defined.*PYJS1003"):
        transpile_llvm_module('''
        from tests.native.model_inputs_fixtures import Setting
        def render(value: Setting) -> str:
            return value.absent
        ''', target="library", entry_point="render")


@pytest.mark.parametrize(("definition", "error"), [
    ("class Root(RootModel[list[int]]): pass", CompilationError),
    # Pydantic creates this class dynamically; definition_error has no source
    # span and retains its documented TypeError fallback with the same message.
    ("Root = RootModel[list[int]]", TypeError),
])
@pytest.mark.parametrize("annotation", ["Root", "list[Root]"])
def test_root_model_inputs_fail_before_foreign_base_lookup(definition, error, annotation):
    with pytest.raises(error, match="native Pydantic inputs do not support RootModel"):
        transpile_llvm_module(f'''
        from pydantic import RootModel
        {definition}
        def render(value: {annotation}) -> str:
            return 'unused'
        ''', target="library", entry_point="render")


def test_unreached_root_model_does_not_block_native_compilation():
    module = transpile_llvm_module('''
        from pydantic import RootModel
        class Root(RootModel[list[int]]): pass
        def render(value: int) -> str:
            return str(value)
    ''', target="library", entry_point="render")
    assert len(module.parameters) == 1


@pytest.mark.parametrize("direct", [False, True])
def test_model_fields_feed_buffered_and_descriptor_dom_renderers(tmp_path, direct):
    source = '''
from tests.native.model_inputs_fixtures import Setting
from pyjs.web.domx import div
from pyjs.web.ssr import render_html
from pyjs.native import write_html_fd
def render(value: Setting) -> str:
    return render_html(div(value.name))
def write(value: Setting, descriptor: int) -> int:
    return write_html_fd(div(value.name), descriptor)
'''
    library = LLVM().compile_library(source, tmp_path, direct=direct,
                                     entry_point="write" if direct else "render")
    try:
        value = Setting(name="a & <b>")
        if direct:
            with tempfile.TemporaryFile() as output:
                assert library.render_to_fd(output.fileno(), value) == 0
                output.seek(0)
                actual = output.read().decode()
        else:
            actual = library.render(value)
        assert actual == "<div>A &amp; &lt;B&gt;</div>"
    finally:
        library.close()
