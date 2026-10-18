import gc
import weakref

import pytest

from pyjs import llvm
from pyjs.analysis.diagnostics import CompilationError
from pyjs.decorators import get_native_decoration
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.memory import compiled_arena_runtime, compiled_heap_runtime
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
    EVALUATION_ORDER_CONTRACT,
    FIELD_ASSIGNMENT_CONTRACT,
    INHERITED_FACTORY_FIELD_CONTRACT,
    INHERITED_FIELD_ASSIGNMENT_CONTRACT,
    LITERAL_FIELD_ASSIGNMENT_CONTRACT,
    MAPPING_ASSIGNMENT_CONTRACT,
    PROPERTY_FIELD_OVERRIDE_CONTRACT,
)
from tests.native.test_runtime_compiler import _consumer_increment


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [FIELD_ASSIGNMENT_CONTRACT, MAPPING_ASSIGNMENT_CONTRACT,
    LITERAL_FIELD_ASSIGNMENT_CONTRACT, INHERITED_FIELD_ASSIGNMENT_CONTRACT, CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
    INHERITED_FACTORY_FIELD_CONTRACT],
    ids=["field", "mapping", "literal_field", "inherited_field", "class_declared_field", "inherited_factory"])
def test_shared_assignment_contract(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(
        contract.source, directory=tmp_path, optimize=optimize,
    )
    assert result.native.returncode == 0, contract.failure(result.native.returncode)


def test_property_field_override_keeps_unsupported_analysis_boundary():
    with pytest.raises(CompilationError, match="Function returns str.*NoneType, not str"):
        transpile_llvm(PROPERTY_FIELD_OVERRIDE_CONTRACT.source)


def test_inline_validates_templates_and_keeps_the_python_fallback():
    @llvm.inline("add i64 {left}, {right}")
    def add(left: int, right: int) -> int:
        return left + right

    assert add(20, 22) == 42
    decoration = get_native_decoration(add)
    assert decoration.kind == "inline"
    assert decoration.template == "add i64 {left}, {right}"
    for template, diagnostic in (
        ("add i64 {left}, {typo}", "not a parameter"),
        ("add i64 {left!r}, {right}", "conversions"),
        ("add i64 {left},\n{right}", "single-line"),
        (None, "single-line"),
    ):
        with pytest.raises(TypeError, match=diagnostic):
            llvm.inline(template)(add)


@pytest.mark.parametrize("optimize", [0, 2])
def test_native_uses_python_bodies_not_javascript_clients(optimize):
    from tests.backend_semantics import CLIENT_IMPLEMENTATIONS_SOURCE
    result = LLVM().assert_matches_python(CLIENT_IMPLEMENTATIONS_SOURCE, optimize=optimize,
                                          sanitizers=("address", "undefined"))
    assert result.native.returncode == 107
    assert not result.native.stderr


def test_inline_keyword_defaults_and_operand_forwarding():
    result = LLVM().assert_matches_python('''
        from pyjs import int8, llvm

        @llvm.inline("sub i64 {value}, {offset}")
        def adjust(value: int, *, offset: int = 8) -> int:
            return value - offset

        @llvm.inline("{value}")
        def narrowed(value: int) -> int8:
            return int8(value)

        def main() -> int:
            return adjust(offset=8, value=50) + int(narrowed(256))
    ''')
    assert result.native.returncode == 42


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Alias", "Annotated[Alias, f'{UNIT}']"])
def test_inline_lifetimes_allow_later_class_and_alias_annotations(tmp_path, optimize, annotation):
    source = '''
        from typing import Annotated
        from pyjs import llvm
        from pyjs.decorators import ParameterLifetime
        from pyjs.native import gc_collect, gc_set_threshold

        UNIT = "native"

        @llvm.inline("select i1 true, ptr {value}, ptr {value}",
                     value=ParameterLifetime.RETURNED)
        def relay(value: Alias) -> Box:
            return value

        class Box:
            def __init__(self, value: str):
                self.value = value

        Alias = Box

        def create() -> Box:
            return relay(Box("retained-" + str(42)))

        def main() -> str:
            gc_set_threshold(1)
            value = create()
            gc_collect()
            return value.value
    '''.replace("value: Alias", f"value: {annotation}")
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                          sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_empty_inline_omits_argument_analysis_and_execution():
    result = LLVM().run_source('''
        from pyjs import llvm

        @llvm.inline("")
        def browser_only(callback: object) -> None:
            raise NotImplementedError

        def unreachable() -> int:
            return {"unsupported"} + 2

        def main() -> int:
            browser_only(unreachable())
            return 42
    ''')
    assert result.returncode == 42
    assert "fn.unreachable" not in result.llvm_ir
    with pytest.raises(CompilationError, match="requires a None return"):
        transpile_llvm('''
            from pyjs import llvm
            @llvm.inline("")
            def wrong() -> int:
                return 1
            def main() -> int:
                return wrong()
        ''')


def test_lazy_native_definitions_preserve_aliases_and_evaluated_constants():
    result = LLVM().assert_matches_python('''
        import ctypes
        from tests.native.imported_program import CALCULATED_OFFSET, IMPORTED_LABEL, IMPORTED_OFFSET

        SIZE = ctypes.sizeof(ctypes.c_int64)

        class HostOnly(ctypes.Structure):
            _fields_ = [("value", ctypes.c_void_p)]

        class Box:
            def __init__(self, value: int):
                self.value = value

        Alias = Box

        def main() -> int:
            if IMPORTED_LABEL != 'answer':
                return 1
            return Alias(SIZE).value + Box(34).value + CALCULATED_OFFSET - IMPORTED_OFFSET - 1
    ''')
    assert result.native.returncode == 42
    assert "HostOnly" not in result.native.llvm_ir
    assert "timedelta" not in result.native.llvm_ir
    assert result.native.llvm_ir.count("%class.Box = type") == 1


def test_union_method_cannot_mix_erased_and_executed_calls():
    with pytest.raises(CompilationError, match="incompatible client lowering"):
        transpile_llvm('''
            from pyjs import llvm

            class Quiet:
                @llvm.inline("")
                def notify(self, value: int) -> None:
                    pass

            class Active:
                def notify(self, value: int) -> None:
                    pass

            def choose(value: Quiet | Active) -> None:
                value.notify(42)

            def main() -> int:
                choose(Quiet())
                choose(Active())
                return 0
        ''')


@pytest.mark.parametrize("body", [
    "values = [value]\nreturn len(values)",
    "print(value)\nreturn value",
    "raise ValueError('failure')",
    "gc_collect()\nreturn value",
])
def test_runtime_helpers_reject_implicit_managed_effects(body):
    source = (
        "from pyjs.native import gc_collect\n"
        "from pyjs.native.runtime.algorithms import _runtime\n"
        "@_runtime\ndef helper(value: int) -> int:\n    "
        + body.replace("\n", "\n    ")
        + "\ndef main() -> int:\n    return helper(4)\n"
    )
    with pytest.raises(LLVMUnsupported, match="runtime helper"):
        transpile_llvm(source)


def test_runtime_compilation_releases_graphs_and_caches_only_text(monkeypatch):
    from pyjs.analysis import analyzer

    references = []
    original = analyzer.analyze_module

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        references.append(weakref.ref(result[0]))
        return result

    monkeypatch.setattr(analyzer, "analyze_module", record)
    first = compile_runtime({"consumer": _consumer_increment})
    assert compile_runtime({"consumer": _consumer_increment}) == first
    for compile_cached in (compiled_arena_runtime, compiled_heap_runtime):
        compile_cached.cache_clear()
        text = compile_cached()
        assert compile_cached() is text
        assert isinstance(text, tuple) and all(isinstance(line, str) for line in text)
    gc.collect()
    assert references and all(reference() is None for reference in references)


def test_runtime_loop_scratch_slots_are_allocated_once():
    for compile_cached in (compiled_arena_runtime, compiled_heap_runtime):
        entry = False
        for line in compile_cached():
            if line.startswith("define "):
                entry = True
            elif line.endswith(":") and line != "block.entry:":
                entry = False
            elif " = alloca " in line:
                assert entry, line


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_expressions_do_not_register_gc_roots(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def scalar_work(n: int) -> int:
            total = 0
            for index in range(n):
                total += (index * 3 + 7) % 11 - (index // 2) * (index % 3) + (1 if index % 5 == 0 else 2)
                total = total * 2 - index + (index + 1) * (index + 2) // (index + 3)
            return total

        def main() -> int:
            gc_collect()
            return scalar_work(10) % 251
    ''', optimize=optimize)
    # Inspect only this helper: the complete module includes the GC runtime.
    function = result.native.llvm_ir.split("define i64 @fn.scalar_work(", 1)[1].split("\n}", 1)[0]
    assert "__expression" not in function
    # The iterator, exception message and exception value payload are roots,
    # not scalar expressions. The payload also retains StopIteration.value.
    assert "alloca [3 x ptr]" in function


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("stored", [False, True], ids=["inlined", "materialized"])
def test_range_bounds_keep_callback_roots_and_materialized_sources(tmp_path, optimize, stored):
    setup = "selected = range(Bound(4))" if stored else ""
    iterable = "selected" if stored else "range(Bound(4))"
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Bound:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        def main() -> str:
            gc_set_threshold(1)
            {setup}
            gc_collect()
            total = 0
            for value in {iterable}:
                gc_collect()
                total += value
            return str(total)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_override_receives_heap_and_roots_receiver(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Base:
            def value(self) -> int:
                return 1

        class Child(Base):
            def __init__(self):
                self.number = 42

            def value(self) -> int:
                gc_collect()
                return self.number

        def read(value: Base) -> int:
            return value.value()

        def main() -> int:
            gc_collect()
            return read(Child())
    ''', optimize=optimize)
    assert result.native.returncode == 42


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("value", ["owner.child", "owner.items[0]", "owner.pair[0]"])
def test_loaded_argument_survives_source_replacement_and_collection(optimize, value):
    source = '''
        from pyjs.native import gc_collect

        class Child:
            def __init__(self, value: int):
                self.value = value

        class Owner:
            def __init__(self):
                self.child = Child(42)
                self.items = [self.child]
                self.pair = (self.child,)

        def replace(owner: Owner) -> int:
            owner.child = Child(77)
            owner.items[0] = owner.child
            owner.pair = (owner.child,)
            gc_collect()
            fresh = Child(99)
            return fresh.value

        def consume(value: Child, ignored: int) -> int:
            return value.value

        def main() -> int:
            owner = Owner()
            return consume(VALUE, replace(owner))
    '''.replace("VALUE", value)
    assert LLVM().assert_matches_python(source, optimize=optimize).native.returncode == 42


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("kind", "instruction", "left", "right", "expected"), [
    ("int8", "add i8", 120, 10, -126),
    ("int64", "add i64", 9007199254740993, 2, 9007199254740995),
    ("float32", "fadd float", 16777216.0, 1.0, 16777216.0),
])
def test_inline_instructions_receive_physical_parameter_widths(
    optimize, kind, instruction, left, right, expected,
):
    result = LLVM().assert_matches_python(f'''
        from pyjs import llvm, {kind}

        @llvm.inline("{instruction} {{left}}, {{right}}")
        def add(left: {kind}, right: {kind}) -> {kind}:
            return left + right

        def compute(left: {kind}, right: {kind}) -> int:
            return int(add(right=right, left=left) == {expected})

        def main() -> int:
            return compute({kind}({left}), {kind}({right}))
    ''', optimize=optimize)
    assert result.native.returncode == 1


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_evaluation_order_contract(optimize):
    result = LLVM().assert_matches_python(
        EVALUATION_ORDER_CONTRACT.source, optimize=optimize,
    )
    assert result.native.returncode == 0, EVALUATION_ORDER_CONTRACT.failure(
        result.native.returncode,
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_managed_object_keeps_pinnable_identity_across_collection(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_pin, gc_unpin

        class Marker:
            pass

        def main() -> int:
            value = Marker()
            gc_pin(value)
            gc_collect()
            gc_unpin(value)
            gc_collect()
            gc_pin(value)
            gc_unpin(value)
            return 42
    ''', optimize=optimize)
    assert result.native.returncode == 42
