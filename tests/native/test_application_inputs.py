"""Nominal application union inputs share the ordinary typed copy-in graph."""

import sys
from copy import deepcopy
from datetime import date

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm_module
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_union_inputs_keep_subclass_dispatch_and_shared_views(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, label: str):
                self.label = label
            def describe(self) -> str:
                return 'base:' + self.label

        class Child(Base):
            def __init__(self, label: str, extra: str):
                super().__init__(label)
                self.extra = extra
            def describe(self) -> str:
                return 'child:' + self.label + ':' + self.extra

        class Other:
            def __init__(self, code: int):
                self.code = code

        def describe(value: Base) -> str:
            return value.describe()

        def render(values: list[Base | Other | str], shared: Child) -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for value in values:
                gc_collect()
                if isinstance(value, Child):
                    rows.append(describe(value) + ':' + str(value is shared))
                elif isinstance(value, Base):
                    rows.append(describe(value))
                elif isinstance(value, Other):
                    rows.append('other:' + str(value.code))
                else:
                    rows.append('text:' + value)
            return '|'.join(rows)
    '''
    library = LLVM().compile_library(source, tmp_path, entry_point="render",
                                     module_name="application_union_inputs", optimize=optimize)
    module = sys.modules["application_union_inputs"]
    try:
        child = module.Child("two", "extra")
        values = [module.Base("one"), child, module.Other(3), "four", child]
        expected = module.render(values, child)
        assert library.render(values, child) == expected == (
            "base:one|child:two:extra:True|other:3|text:four|child:two:extra:True"
        )
        # Neither a same-named impostor nor an unreached subclass may acquire
        # a native class identity from its spelling or structural attributes.
        impostor = type("Base", (), {"label": "fake"})()
        class Unreached(module.Base):
            pass
        for invalid in (impostor, Unreached("late"), {"label": "ambiguous"}):
            with pytest.raises(TypeError, match=r"values\[0\] must match"):
                library.render([invalid], child)
            assert library.render(values, child) == expected
    finally:
        library.close()


def test_application_union_inputs_reject_ambiguous_python_generic_classes():
    with pytest.raises(LLVMUnsupported, match="cannot distinguish specializations of the same host class"):
        transpile_llvm_module('''
            class Box[T]:
                def __init__(self, item: T):
                    self.item = item
            def render(value: Box[int] | Box[str]) -> str:
                return 'value'
        ''', target="library", entry_point="render")


def test_implicit_generic_subclass_ambiguity_names_the_class():
    with pytest.raises(LLVMUnsupported, match="same host class: Child"):
        transpile_llvm_module('''
            class Base:
                pass
            class Child[T](Base):
                def __init__(self, item: T):
                    self.item = item
            def render(value: Base | str) -> str:
                reached: list[Base] = [Child[int](1), Child[str]('two')]
                return str(len(reached))
        ''', target="library", entry_point="render")


@pytest.mark.parametrize("annotation,expression", [
    ("Any", "str(value)"),
    ("list[Any]", "str(value[0])"),
    ("Box[Any]", "str(value.item)"),
    ("Box[Any] | str", "value if isinstance(value, str) else str(value.item)"),
    ("Box[Any] | Box[int]", "str(value.item)"),
])
def test_any_host_inputs_reject_instead_of_becoming_empty_records(annotation, expression):
    with pytest.raises(LLVMUnsupported, match="concrete type, not typing.Any") as caught:
        transpile_llvm_module(f'''
            from typing import Any
            from pydantic import BaseModel
            class Box[T](BaseModel):
                item: T
            def render(value: {annotation}) -> str:
                return {expression}
        ''', target="library", entry_point="render")
    assert caught.value.node.lineno == 1  # The entry parameter, relative to its function.


@pytest.mark.parametrize("optimize", [0, 2])
def test_single_generic_application_union_arm_preserves_its_fields(tmp_path, optimize):
    library = LLVM().compile_library('''
        class Box[T]:
            def __init__(self, item: T):
                self.item = item
        def render(value: Box[int] | str) -> str:
            if isinstance(value, str):
                return value
            return str(value.item + 1)
    ''', tmp_path, entry_point="render", module_name="generic_application_inputs", optimize=optimize)
    module = sys.modules["generic_application_inputs"]
    try:
        for value in (module.Box(41), "plain"):
            assert library.render(value) == module.render(value)
        with pytest.raises(TypeError, match="value.item must be int"):
            library.render(module.Box("wrong"))
        assert library.render(module.Box(2)) == "3"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("first_type,second_type,first_value,second_value", [
    ("int", "str", 42, "plain"),
    ("list[int | None]", "list[str]", [42, None], ["plain"]),
    ("list[OptionalNumber | str]", "list[float]", [42, None, "nested"], [1.5]),
    ("tuple[int, ...]", "tuple[str, ...]", (1, 2), ("a", "b")),
    ("Literal['x', 'y']", "Literal['a', 'b']", "y", "a"),
    ("date", "str", date(2024, 2, 29), "plain"),
])
def test_distinct_generic_model_union_arms_preserve_fields_and_aliases(
    tmp_path, optimize, first_type, second_type, first_value, second_value,
):
    # Read each concrete payload independently: joining differently typed lists
    # or tuples into one runtime union is a separate, diagnosed storage limit.
    first_text = "first.item.isoformat()" if first_type == "date" else "str(first.item)"
    library = LLVM().compile_library(f'''
        from datetime import date
        from typing import Literal
        from pydantic import BaseModel
        from pyjs.native import gc_collect
        type OptionalNumber = int | None
        type First = {first_type}
        type Second = {second_type}
        class Box[T](BaseModel):
            item: T
        def render(value: Box[First] | Box[Second], first: Box[First], second: Box[Second]) -> str:
            gc_collect()
            return str((value is first, value is second)) + ':' + {first_text} + ':' + str(second.item)
    ''', tmp_path, module_name="nominal_union_models", entry_point="render", optimize=optimize)
    module = sys.modules["nominal_union_models"]
    first = module.Box[module.First](item=first_value)
    second = module.Box[module.Second](item=second_value)
    try:
        assert type(first) is not type(second)
        for value in (first, second):
            assert library.render(value, first, second) == module.render(value, first, second)
        with pytest.raises(TypeError, match="must match"):
            library.render(module.Box[float](item=1.0), first, second)
        assert library.render(first, first, second) == module.render(first, first, second)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_union_inputs_own_retained_graphs_and_recover(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, values: list[str]):
                self.values = values
        saved: list[Box | str | int | None] = []
        def render(value: Box | str | int | None, plain: list[str], fail: bool) -> str:
            gc_set_threshold(1)
            same = False
            if isinstance(value, Box):
                same = value.values is plain
                value.values.append('native')
            if fail:
                raise ValueError('after mutation')
            saved.append(value)
            gc_collect()
            rows: list[str] = []
            for item in saved:
                rows.append(str(item.values) if isinstance(item, Box) else repr(item))
            return str(same) + ':' + '|'.join(rows)
    ''', tmp_path, entry_point="render", module_name="retained_application_inputs", optimize=optimize)
    module = sys.modules["retained_application_inputs"]
    shared = ["host"]
    box = module.Box(shared)
    try:
        for value, fail in ((box, False), ("text", False), (box, True),
                            (None, False), (True, False), (box, False)):
            arguments = (value, shared, fail)
            if fail:
                with pytest.raises(ValueError, match="after mutation"):
                    module.render(*deepcopy(arguments))
                with pytest.raises(LLVMRuntimeError, match="after mutation"):
                    library.render(*arguments)
            else:
                assert library.render(*arguments) == module.render(*deepcopy(arguments))
            assert shared == ["host"]
        with pytest.raises(TypeError, match=r"value.values\[0\] must be str"):
            library.render(module.Box([object()]), shared, False)
        assert library.render(7, shared, False) == module.render(7, shared, False)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_foreign_union_subclass_copy_installs_identity_under_asan(tmp_path, optimize):
    module = transpile_llvm_module('''
        from pyjs.native import gc_collect
        class Base:
            def __init__(self, label: str):
                self.label = label
            def describe(self) -> str:
                return self.label
        class Child(Base):
            def __init__(self, label: str, count: int):
                super().__init__(label)
                self.count = count
            def describe(self) -> str:
                gc_collect()
                return self.label + str(self.count)
        def render(value: Base | str) -> str:
            if isinstance(value, Child):
                gc_collect()
                return value.describe()
            return 'wrong member'
    ''', target="library", entry_point="render")
    union = module.parameters[0].value_type.resolve(module.type_definitions)
    child = next(member for member in union.members if member.name == "Child")
    assert child.identity and [field.name for field in child.fields] == ["label", "count"]
    source = module.llvm_ir + '''
        @test.bytes = private constant [6 x i8] c"child:"
        @test.text = private constant %pyjs.string { i64 6, ptr @test.bytes }
        @test.child = private constant { ptr, ptr, i64 } { ptr null, ptr @test.text, i64 42 }
        @test.error.count = global i32 0
        define void @test.error(ptr %trace, ptr %message, ptr %type) {
            store i32 1, ptr @test.error.count
            ret void
        }
        define i32 @main() {
            %heap = call ptr @pyjs_gc_new()
            %status = call i32 @pyjs_render_host_to_fd(ptr %heap, i32 1, ptr @test.error, ptr @test.union)
            call void @pyjs_gc_delete(ptr %heap)
            %error = load i32, ptr @test.error.count
            %result = or i32 %status, %error
            ret i32 %result
        }
    ''' + f'@test.union = private constant {{ i64, i64 }} {{ i64 {child.runtime_tag}, i64 ptrtoint (ptr @test.child to i64) }}\n'
    result = LLVM()._run_ir(source, tmp_path, name="union-input", optimize=optimize,
                            pass_fds=(), sanitizers=("address", "undefined"), timeout=10, artifacts=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "child:42"
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_container_union_preserves_nominal_member_aliases(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect
        class Box:
            def __init__(self, label: str):
                self.label = label
        type Tree = Box | list[Tree] | None
        def render(value: Tree, box: Box) -> str:
            gc_collect()
            if isinstance(value, list):
                return str((value[0] is value, value[1] is box))
            if isinstance(value, Box):
                return value.label + ':' + str(value is box)
            return 'none'
    ''', tmp_path, entry_point="render", module_name="recursive_application_inputs", optimize=optimize)
    module = sys.modules["recursive_application_inputs"]
    box = module.Box("shared")
    cycle = []
    cycle.extend([cycle, box])
    try:
        for value in (cycle, box, None):
            assert library.render(value, box) == module.render(value, box)
        with pytest.raises(TypeError, match="must match"):
            library.render([cycle, object()], box)
        assert library.render(cycle, box) == "(True, True)"
    finally:
        cycle.clear()
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_stdlib_record_union_uses_public_host_classes(tmp_path, optimize):
    from datetime import date
    from uuid import UUID

    library = LLVM().compile_library('''
        from datetime import date
        from uuid import UUID
        def render(value: date | UUID | str) -> str:
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, UUID):
                return value.hex
            return value
    ''', tmp_path, entry_point="render", module_name="stdlib_union_inputs", optimize=optimize)
    module = sys.modules["stdlib_union_inputs"]
    try:
        for value in (date(2024, 2, 29), UUID(int=42), "plain"):
            assert library.render(value) == module.render(value)
    finally:
        library.close()
