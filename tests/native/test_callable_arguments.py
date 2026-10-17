import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import CALLABLE_INPUT_CONTRACT
from tests.native.allocation_support import run_allocation_case


def test_shared_callable_input_contract(tmp_path):
    comparison = LLVM().assert_matches_python(CALLABLE_INPUT_CONTRACT.source, directory=tmp_path,
                                            sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_unrelated_plain_input_domains_do_not_enable_gc(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        def increment(value: int) -> int:
            return value + 1
        def predicate(value: float) -> bool:
            return value > 0.5
        def run_integer(callback: Callable[[int], int]) -> int:
            result = 0
            for index in range(100):
                result = callback(result)
            return result
        def run_float(callback: Callable[[float], bool]) -> bool:
            return callback(1.5)
        def main() -> int:
            return run_integer(increment) if run_float(predicate) else 0
    ''', directory=tmp_path, optimize=optimize)
    assert comparison.native.stderr == ""
    # Whole IR contains runtime scaffolding; this checks the absence of an
    # unnecessary managed heap for independent scalar signatures, not its text.
    assert '@pyjs.gc.' not in (tmp_path / 'program.ll').read_text()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("optional_inputs", [False, True])
def test_unrelated_optional_domains_do_not_enable_gc(tmp_path, optimize, optional_inputs):
    integer = "int | None" if optional_inputs else "int"
    floating = "float | None" if optional_inputs else "float"
    result = "int" if optional_inputs else "int | None"
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        def half(value: {integer}) -> {result}:
            return 0 if value is None else value // 2
        def positive(value: {floating}) -> int:
            return 0 if value is None else 1
        def run_integer(callback: Callable[[{integer}], {result}]) -> int:
            total = 0
            for index in range(100):
                value = callback(index)
                if value is not None:
                    total += value
            return total
        def run_float(callback: Callable[[{floating}], int]) -> int:
            return callback(1.5)
        def main() -> int:
            return (run_integer(half) + run_float(positive)) % 256
    ''', directory=tmp_path, optimize=optimize)
    assert comparison.native.stderr == ""
    # An optional result alone cannot make incompatible int/float inputs
    # adaptable; optional inputs also retain their distinct numeric ABI.
    assert '@pyjs.gc.' not in (tmp_path / 'program.ll').read_text()


@pytest.mark.parametrize("parameters,returned,target_parameters,target_result", [
    ("value: list[object]", "str", "list[int]", "str"),
    ("value: float | None", "str", "int | None", "str"),
    ("", "int | None", "", "float | None"),
])
def test_adapter_diagnostic_includes_authored_source_location(parameters, returned, target_parameters, target_result):
    value = "'x'" if returned == "str" else "1"
    source = (
        "from collections.abc import Callable\n"
        f"def broad({parameters}) -> {returned}:\n"
        f"    return {value}\n\n\n\n"
        f"def factory() -> Callable[[{target_parameters}], {target_result}]:\n"
        "    return broad\n"
        "def main() -> int:\n"
        "    factory()\n"
        "    return 0\n"
    )
    with pytest.raises(LLVMUnsupported) as caught:
        transpile_llvm(source, filename='callback_location.py')
    assert caught.value.__notes__ == [
        'Source location: callback_location.py:8:12 (factory; reported line above is function-relative)'
    ]


@pytest.mark.parametrize("binding,column", [
    ("method = receiver.read", 14),
    ("method = partial(receiver.read, 1)", 22),
    ("return partial(receiver.read, 1)", 20),
])
def test_preparation_diagnostic_locates_the_authored_method_binding(binding, column):
    source = (
        "from functools import partial\n"
        "class Left:\n"
        "    def read(self, value: int, extra: str = 'x') -> str:\n"
        "        return str(value) + extra\n"
        "class Right:\n"
        "    def read(self, value: int, extra: int) -> str:\n"
        "        return str(value + extra)\n"
        "def main():\n"
        "    receiver: Left | Right = Left()\n"
        f"    {binding}\n"
    )
    with pytest.raises(LLVMUnsupported) as caught:
        transpile_llvm(source, filename="method_binding.py")
    assert caught.value.__notes__ == [
        f"Source location: method_binding.py:10:{column} "
        "(main; reported line above is function-relative)"
    ]


@pytest.mark.parametrize("optimize", [0, 2])
def test_input_adapters_cross_fields_collections_and_nullable_storage(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def show(value: object) -> str:
            gc_collect()
            return repr(value)
        class Holder:
            def __init__(self, callback: Callable[[int], str]):
                self.callback = callback
        def consume(callback: Callable[[int], str] | None) -> str:
            gc_collect()
            return 'absent' if callback is None else callback(3)
        def main() -> str:
            gc_set_threshold(1)
            holder = Holder(show)
            callbacks: list[Callable[[int], str]] = [show, holder.callback]
            mapping: dict[str, Callable[[int], str]] = {'show': show}
            gc_collect()
            assert holder.callback is show and callbacks[0] is show
            return holder.callback(1) + callbacks[1](2) + mapping['show'](4) + consume(show) + consume(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_arguments_box_scalars_references_and_nullable_values(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def show(value: object) -> str:
            gc_collect()
            return repr(value)

        def number() -> Callable[[int], str]:
            return show

        def items() -> Callable[[list[int]], str]:
            return show

        def optional() -> Callable[[str | None], str]:
            return show

        def union() -> Callable[[int | str | None], str]:
            return show

        class Box:
            def __repr__(self) -> str:
                return "Box()"

        def record() -> Callable[[Box], str]:
            return show

        def main() -> str:
            gc_set_threshold(1)
            scalar = number()
            sequence = items()
            maybe = optional()
            mixed = union()
            box = record()
            gc_collect()
            assert scalar is show and sequence is show
            return repr((scalar(42), sequence([1, 2]), maybe(None), maybe("hello"),
                         mixed(None), mixed(7), mixed("text"), box(Box())))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_argument_and_result_adapters_preserve_effects_and_void_calls(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Recorder:
            def __init__(self):
                self.values: list[object] = []

            def append(self, value: object) -> None:
                gc_collect()
                self.values.append(value)

            def read(self, value: object, fail: bool) -> str:
                self.values.append(value)
                gc_collect()
                if fail:
                    raise ValueError("callback failed")
                return repr(value)

        def sink(recorder: Recorder) -> Callable[[list[int]], None]:
            return recorder.append

        def combined(recorder: Recorder) -> Callable[[int, bool], object]:
            return recorder.read

        def main() -> str:
            gc_set_threshold(1)
            recorder = Recorder()
            append = sink(recorder)
            read = combined(recorder)
            append([42] * 64)
            value: object = None
            for fail in [True, False, True, False]:
                saved = value
                try:
                    value = read(7, fail)
                except ValueError:
                    assert value is saved
                gc_collect()
            return repr((recorder.values, value))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_arguments_adapt_nested_callback_contracts(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def show(value: object) -> str:
            gc_collect()
            return repr(value)

        def invoke(callback: Callable[[int], object], values: list[int]) -> str:
            gc_collect()
            return repr((callback(42), list(values), list(values)))

        def factory() -> Callable[[Callable[[object], str], list[int]], str]:
            return invoke

        def main() -> str:
            gc_set_threshold(1)
            callback = factory()
            gc_collect()
            return callback(show, [1, 2])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_parameter_adapters_unwrap_custom_dom_elements(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement

        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
                self.append("panel")

        def show(value: Element | None) -> str:
            gc_collect()
            return "missing" if value is None else value.textContent

        def factory() -> Callable[[Panel | None], str]:
            return show

        def main() -> str:
            gc_set_threshold(1)
            callback = factory()
            panel = Panel()
            gc_collect()
            return callback(panel) + callback(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_argument_boxing_failures_do_not_enter_callback(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Callable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def consume(left: object, right: object, events: list[str]) -> None:
            gc_collect()
            events.append(repr((left, right)))

        def factory() -> Callable[[int, list[int], list[str]], None]:
            return consume

        def main() -> int:
            callback = factory()
            events: list[str] = []
            values = [1, 2]
            for stage in [1, 2]:
                before = len(events)
                caught = False
                arm(stage)
                try:
                    callback(42, values, events)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or len(events) != before:
                    return 1
                callback(42, values, events)
                if events[-1] != "(42, [1, 2])":
                    return 2
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("argument,value", [("int", "42"), ("int | str | None", "'hello'"),
                                           ("list[int]", "[1, 2]"), ("int | None", "None")])
def test_reassigned_input_view_checks_captured_arguments(tmp_path, optimize, argument, value):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def broad(value: object) -> str:
            gc_collect()
            return repr(value)

        def narrow(value: {argument}) -> str:
            gc_collect()
            return repr(value)

        def main() -> str:
            gc_set_threshold(1)
            view: Callable[[{argument}], str] = broad
            view = broad
            # Keep the broad descriptor explicitly: assigning it to a narrow
            # view does not make that view accept arbitrary objects again.
            original: Callable[[object], str] = broad
            deferred = lambda: view({value})
            before = deferred()
            view = narrow
            gc_collect()
            middle = deferred()
            view = broad
            return before + middle + deferred() + original('original')
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("accepted,argument", [("int | str", "42"), ("int | None", "42")])
def test_captured_input_view_checks_tag_and_presence(tmp_path, optimize, accepted, argument):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        def broad(value: {accepted}) -> str:
            return repr(value)
        def narrow(value: int) -> str:
            return repr(value)
        def main() -> str:
            view: Callable[[int], str] = broad
            view = broad
            deferred = lambda: view({argument})
            before = deferred()
            view = narrow
            return before + deferred()
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("accepted,expected,value,definitions", [
    ("object", "int", "'wrong'", ""),
    ("int | str", "int", "'wrong'", ""),
    ("int | None", "int", "None", ""),
    ("Parent", "Child", "Parent()", '''
        class Parent:
            pass
        class Child(Parent):
            pass
    '''),
])
def test_declared_input_view_rejects_incompatible_captured_call(accepted, expected, value, definitions):
    # Reassignment now preserves the declared input signature. This formerly
    # reached a native runtime guard through an incorrectly widened proof;
    # the shared analyzer must reject it before generating any native code.
    with pytest.raises(CompilationError, match="Callable argument 1 expects"):
        transpile_llvm(f'''
        from collections.abc import Callable
        {definitions}
        def broad(value: {accepted}, events: list[int]) -> str:
            events.append(1)
            return 'entered'
        def narrow(value: {expected}, events: list[int]) -> str:
            events.append(1)
            return 'entered'
        def main() -> str:
            events: list[int] = []
            view: Callable[[{expected}, list[int]], str] = broad
            view = broad
            deferred = lambda: view({value}, events)
            view = narrow
            try:
                result = deferred()
            except TypeError:
                result = 'rejected'
            return result + ':' + str(len(events))
    ''')


@pytest.mark.parametrize("accepted,expected,message", [
    ("list[object]", "list[int]", "collection views require matching"),
    ("float", "int", "explicit numeric conversion"),
    ("int", "bool", "explicit numeric conversion"),
])
def test_callback_input_views_do_not_reinterpret_storage(accepted, expected, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            from collections.abc import Callable
            def consume(value: {accepted}) -> int:
                return 7
            def factory() -> Callable[[{expected}], int]:
                return consume
            def main() -> int:
                factory()
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_input_views_preserve_portable_parameters_and_nested_captures(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def show(value: object) -> str:
            gc_collect()
            return repr(value)
        def broad(left: Callable[[int], object], right: Callable[[int], object]) -> str:
            gc_collect()
            return repr((left(7), right(8)))
        def narrow(left: Callable[[object], str], right: Callable[[object], str]) -> str:
            gc_collect()
            return left(7) + right(8)
        def other(value: object) -> str:
            gc_collect()
            return str(value)
        def portable(value: int8, other: object) -> int8:
            gc_collect()
            return value + int8(1)
        def factory() -> Callable[[int8, str], int8]:
            return portable
        def main() -> str:
            gc_set_threshold(1)
            view: Callable[[Callable[[object], str], Callable[[object], str]], str] = broad
            view = broad
            deferred = lambda: view(show, show)
            # These descriptors have no prior inverse view to cancel: both
            # nested argument projections must actually allocate and survive GC.
            fresh = lambda: view(show, other)
            before = deferred()
            view = narrow
            middle = deferred()
            view = broad
            allocated = fresh()
            return before + middle + allocated + deferred() + str(factory()(int8(127), 'value'))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_stored_input_view_preserves_dom_wrapper_conversion(tmp_path):
    # The declared Panel input survives reassignment, so its adapter can still
    # unwrap Panel for broad(). No reverse opaque-to-wrapper proof is needed.
    LLVM().assert_matches_python('''
            from collections.abc import Callable
            from pyjs.web.dom import Element
            from pyjs.web.domx import CustomElement
            class Panel(CustomElement):
                def __init__(self):
                    super().__init__()
            def broad(value: Element) -> int:
                return 1
            def main() -> int:
                view: Callable[[Panel], int] = broad
                view = broad
                return view(Panel())
        ''', directory=tmp_path, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_repeated_input_adapters_have_bounded_retained_heap(tmp_path, optimize):
    from pyjs.native.runtime import collector, heap
    from pyjs.native.runtime.pointers import Pointer
    from tests.native.runtime_support import runtime_functions

    library = LLVM().compile_library('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_pin, gc_set_threshold
        class Box:
            def __init__(self, prefix: str):
                self.prefix = prefix
            def show(self, value: object) -> str:
                return self.prefix + repr(value)
        def main(count: int) -> str:
            gc_set_threshold(1)
            callback = Box('box:').show
            view: Callable[[int], str] = callback
            view = callback
            for index in range(count):
                original: Callable[[object], str] = callback
                view = original
                gc_collect()
            assert view is callback
            gc_pin(view)
            return view(42)
    ''', tmp_path, optimize=optimize)
    try:
        assert library.render(100) == 'box:42'
        collect = runtime_functions({"pyjs.gc.try.collect": collector.try_collect}, library._library)
        assert collect("pyjs.gc.try.collect", Pointer(library._heap))
        # Only the pinned view, its original bound descriptor and receiver
        # remain. Retaining every replaced adapter would exceed 100 allocations.
        assert heap._Heap.from_address(library._heap).count <= 4
    finally:
        library.close()
