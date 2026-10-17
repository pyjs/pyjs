import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("other_type", "other_value"), [
    ("int", "value"), ("bool", "value % 2 == 1"), ("float", "float(value)"),
    ("str", "str(value)"), ("bytes", "b'hello'"), ("None", "None"),
])
def test_exact_signature_callback_does_not_reserve_adapter_gc(tmp_path, optimize, other_type, other_value):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        def step(x: int) -> int:
            return (x * 31 + 7) % 1000003
        def apply(callback: Callable[[int], int], count: int) -> int:
            result = 0
            for index in range(count):
                result = callback(result + index)
            return result
        def other(value: int) -> {other_type}:
            return {other_value}
        def visit(callback: Callable[[int], {other_type}]) -> None:
            callback(3)
        def main() -> str:
            visit(other)
            return str(apply(step, 500))
    ''', directory=tmp_path, optimize=optimize)
    assert comparison.native.stderr == ""
    # The complete IR includes string/runtime helpers. This contract is about
    # the absence of an unnecessary managed heap, not exact runtime scaffolding.
    assert "@pyjs.gc." not in (tmp_path / "program.ll").read_text()


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_callback_result_is_not_a_plain_builtin_reservation(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from typing import Literal
        def answer(value: int) -> Literal["yes"]:
            return "yes"
        def consume(callback: Callable[[int], str]) -> str:
            return callback(1)
        def main() -> str:
            return consume(answer)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_captured_callback_integer_abi_rejects_bool_and_recovers(tmp_path, optimize):
    comparison = LLVM().compare_with_python('''
        from collections.abc import Callable
        def first() -> int:
            return 1
        def flag() -> bool:
            return True
        def main() -> str:
            view: Callable[[], object] = first
            view = first
            deferred = lambda: view() + 1
            view = flag
            try:
                outcome = str(deferred())
            except TypeError as error:
                assert str(error) == "callable result is not an integer"
                outcome = "rejected"
            view = first
            return outcome + ":" + str(deferred())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # This is an intentional ABI boundary, not parity: plain erased-local
    # narrowing can retain a bool tag, but Callable[[], int] returns only i64.
    assert comparison.python.returncode == comparison.native.returncode == 0
    assert comparison.python.stderr == comparison.native.stderr == ""
    assert comparison.python.stdout == "2:2"
    assert comparison.native.stdout == "rejected:2"


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("result", ["object", "int | None", "int | str"])
def test_reassigned_callable_preserves_storage_abi(tmp_path, optimize, result):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def first() -> int:
            return 1

        def second() -> int:
            gc_collect()
            return 2

        def consume(callback: Callable[[], object]) -> str:
            gc_collect()
            return repr(callback())

        class Box:
            def __init__(self, value: int):
                self.value = value
            def read(self) -> int:
                gc_collect()
                return self.value

        def main() -> str:
            gc_set_threshold(1)
            view: Callable[[], {result}] = first
            before = view()
            view = second
            direct = view() + 10
            saved: Callable[[], int] = view
            deferred = lambda: view()
            forwarded = consume(view)
            callbacks: list[Callable[[], int]] = [view]
            gc_collect()
            assert view is second
            view = Box(3).read
            return repr((before, direct, saved(), deferred(), forwarded,
                         callbacks[0](), view(), consume(view)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_reassigned_nested_callable_result_view(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def answer() -> int:
            gc_collect()
            return 42
        def factory() -> Callable[[], int]:
            return answer
        def main() -> str:
            gc_set_threshold(1)
            view: Callable[[], Callable[[], object]] = factory
            view = factory
            result = view()
            gc_collect()
            assert result is answer
            return str(result() + 1)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("result", ["object", "int | None", "int | str"])
def test_captured_narrowed_callback_projects_an_unadapted_replacement(tmp_path, optimize, result):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def first() -> int:
            return 1
        def wide() -> {result}:
            gc_collect()
            return 42
        def main() -> str:
            gc_set_threshold(1)
            view: Callable[[], {result}] = first
            view = first
            deferred = lambda: view() + 1
            view = wide
            return str(deferred())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_reassigned_optional_callback_views_preserve_absence(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def answer() -> int:
            gc_collect()
            return 42
        def maybe(present: bool) -> Callable[[], int] | None:
            return answer if present else None
        def consume(callback: Callable[[], int] | None) -> str:
            gc_collect()
            return str(callback()) if callback is not None else "absent"
        def main() -> str:
            gc_set_threshold(1)
            view: Callable[[], object] | None = answer
            factory: Callable[[bool], Callable[[], object] | None] = maybe
            factory = maybe
            output = ""
            for present in [False, True, False, True]:
                view = maybe(present)
                output += consume(view)
                output += consume(factory(present))
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("actual", "value"), [
    ("bool", "True"), ("float", "1.5"), ("str", "'hello'"),
    ("None", "None"), ("list[int]", "[1, 2]"), ("int | None", "None"),
])
def test_reassigned_erased_callback_projects_its_result(tmp_path, optimize, actual, value):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect
        def answer() -> {actual}:
            gc_collect()
            return {value}
        def main() -> str:
            view: Callable[[], object] = answer
            view = answer
            saved: Callable[[], {actual}] = view
            return repr((view(), saved()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_view_roundtrips_do_not_retain_adapter_chains(tmp_path, optimize):
    from pyjs.native.runtime import collector, heap
    from pyjs.native.runtime.pointers import Pointer
    from tests.native.runtime_support import runtime_functions

    library = LLVM().compile_library('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_pin, gc_set_threshold
        class Box:
            def __init__(self, value: int):
                self.value = value
            def read(self) -> int:
                return self.value
        def main(count: int) -> str:
            gc_set_threshold(1)
            answer = Box(42).read
            view: Callable[[], object] = answer
            view = answer
            gc_collect()
            for index in range(count):
                narrowed: Callable[[], int] = view
                view = narrowed
                gc_collect()
            assert view is answer
            gc_pin(view)
            return str(view())
    ''', tmp_path, optimize=optimize)
    try:
        assert library.render(100) == "42"
        invoke = runtime_functions({"pyjs.gc.try.collect": collector.try_collect}, library._library)
        assert invoke("pyjs.gc.try.collect", Pointer(library._heap))
        # Only the pinned view survives the frame; inverse conversions must
        # not retain a chain whose length grows with the number of assignments.
        assert heap._Heap.from_address(library._heap).count <= 4
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_lambda_results_keep_narrowed_boolean_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
import operator
from typing import cast, overload
from pyjs.native import gc_collect, gc_set_threshold
class Value:
    @overload
    def __add__(self, other: int) -> int: ...
    @overload
    def __add__(self, other: str) -> str: ...
    def __add__(self, other: int | str) -> int | str:
        gc_collect()
        return True if isinstance(other, int) else other
def main() -> str:
    gc_set_threshold(1)
    values: list[object] = [True, 7, "text"]
    narrowed = list(map(lambda value: value if isinstance(value, int) else 0, values))
    optional = list(map(lambda value: value if isinstance(value, int) else None, values))
    items = [Value(), Value()]
    calls = list(map(lambda item: operator.add(item, 1) if True else 0, items))
    converted = list(map(lambda item: int(operator.add(item, 1)), items))
    captured: object = True
    read = lambda: cast(int, captured)
    gc_collect()
    return repr((narrowed, optional, calls, converted, read()))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["min", "max"])
def test_outlined_extrema_keep_specialized_builtin_result_and_live_keys(tmp_path, optimize, operation):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Rank:
            def __init__(self, value: int):
                self.value = value
            def __gt__(self, other: Rank) -> bool:
                gc_collect()
                return self.value > other.value
        def rank(value: int) -> Rank:
            gc_collect()
            return Rank(value)
        def consume(callback: Callable[[int], int]) -> list[int]:
            return list(map(callback, [4, 7]))
        def main() -> str:
            gc_set_threshold(1)
            keyed: Callable[[int], int] = lambda stop: {operation}(range(stop), key=rank)
            plain: Callable[[int], int] = lambda stop: {operation}(range(stop))
            first: Callable[[int], int] = lambda stop: next(iter(range(stop)))
            return str((consume(keyed), consume(plain), consume(first)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_lambda_accounts_for_later_static_overrides(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs.native import gc_collect
class Base:
    @staticmethod
    def read() -> int:
        return 1
class Child(Base):
    @staticmethod
    def read() -> bool:
        gc_collect()
        return True
def invoke(value: Base, choose: bool) -> str:
    callback = lambda: value.read() if choose else Base.read()
    direct: Callable[[], int] = lambda: Base.read()
    return str(callback()) + str(direct())
def main() -> str:
    # Analyze invoke before discovering the subclass constructor. Class-qualified
    # calls keep their exact integer ABI; instance calls must permit late bool.
    return invoke(Base(), True) + invoke(Child(), True) + invoke(Child(), False)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_lambda_adaptation_keeps_explicit_integer_contract(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from typing import cast
from pyjs import int8, int64
from pyjs.native import gc_collect, gc_set_threshold
def invoke(callback: Callable[[], int]) -> str:
    gc_collect()
    return str(callback())
def main() -> str:
    gc_set_threshold(1)
    value: object = True
    inferred = lambda: cast(int, value)
    direct = str(inferred())
    converted = invoke(lambda: int(inferred()))
    narrow = list(map(lambda item: item + int8(1), [int8(127)]))
    wide = list(map(lambda item: item + int64(1), [int64(9007199254740993)]))
    return repr((direct, converted, narrow, wide))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_inferred_lambda_requires_conversion_for_integer_only_callback():
    with pytest.raises(LLVMUnsupported, match="narrowed int may be bool; convert with int"):
        transpile_llvm('''
from collections.abc import Callable
from typing import cast
def invoke(callback: Callable[[], int]) -> int:
    return callback()
def main() -> int:
    value: object = True
    return invoke(lambda: cast(int, value))
''')


@pytest.mark.parametrize("expression", ["value.read()", "Base.read()", "int(value.read())"])
def test_static_lambda_integer_contract_without_boolean_overrides(tmp_path, expression):
    source = f'''
from collections.abc import Callable
class Base:
    @staticmethod
    def read() -> int:
        return 7
def invoke(value: Base) -> int:
    callback: Callable[[], int] = lambda: {expression}
    return callback()
def main() -> int:
    return invoke(Base())
'''
    comparison = LLVM().assert_matches_python(source, directory=tmp_path,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("postponed", [False, True])
def test_integer_static_lambdas_support_collections_arithmetic_and_inherited_calls(tmp_path, optimize, postponed):
    source = '''
from collections.abc import Callable
Integer = int
class Base:
    @staticmethod
    def read() -> int:
        return 5
    def callbacks(self) -> list[Callable[[], int]]:
        return [lambda: self.read()]
class Inherited(Base):
    pass
class Changed(Base):
    @staticmethod
    def read() -> Integer:
        return 7
class Unused(Base):
    @staticmethod
    def read() -> int:
        return nonexistent_name
def invoke(value: Base) -> str:
    direct: Callable[[], int] = lambda: value.read()
    inferred = lambda: value.read()
    values: list[int] = [inferred()]
    mapped: list[int] = list(map(lambda item: item.read(), [value]))
    total: int = sum(map(lambda item: item.read(), [value]))
    return repr((values, mapped, total, inferred() + 1, direct(),
                 [callback() for callback in value.callbacks()]))
def main() -> str:
    # Later constructors must not change earlier integer-only lambda storage.
    return invoke(Base()) + invoke(Inherited()) + invoke(Changed())
'''
    if postponed:
        source = "from __future__ import annotations\n" + source
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["collections.Missing", '"collections.Missing"', '\'int[\''])
def test_unreached_static_override_annotation_failure_is_conservative(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python(f'''
import collections
class Base:
    @staticmethod
    def read() -> int:
        return 1
class Unused(Base):
    @staticmethod
    def read() -> {annotation}:
        return nonexistent_name
def main() -> str:
    item = Base()
    # Do not reach Unused: evaluating its annotation is only an inference aid.
    return repr(list(map(lambda value: value.read(), [item])))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_boolean_capable_inferred_lambda_arithmetic_reports_numeric_conversion(tmp_path, optimize):
    source = '''
def main() -> str:
    value: object = True
    callback = lambda: value if isinstance(value, int) else 0
    return repr((callback() + 1, str(callback())))
'''
    with pytest.raises(LLVMUnsupported, match="narrowed int may be bool; convert with int"):
        transpile_llvm(source)
    comparison = LLVM().assert_matches_python(source.replace("callback() + 1", "int(callback()) + 1"),
                                              directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_results_at_returns_arguments_fields_and_collections(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def answer() -> int:
            gc_collect()
            return 42

        def empty() -> None:
            gc_collect()

        def factory() -> Callable[[], int | None]:
            return answer

        def nested() -> Callable[[], Callable[[], int]]:
            return lambda: answer

        def nested_factory() -> Callable[[], Callable[[], Callable[[], object]]]:
            return nested

        def consume(callback: Callable[[], object]) -> str:
            gc_collect()
            return repr(callback())

        def consume_number(callback: Callable[[], int]) -> float:
            gc_collect()
            return float(callback()) + 0.5

        def maybe(present: bool) -> Callable[[], int] | None:
            return answer if present else None

        def optional(present: bool) -> Callable[[], object] | None:
            return maybe(present)

        class Holder:
            def __init__(self, callback: Callable[[], object]):
                self.callback = callback

        def main() -> str:
            gc_set_threshold(1)
            holder = Holder(answer)
            callback: Callable[[], int | None] = empty
            first = callback()
            callback = factory()
            other = nested_factory()
            callbacks: list[Callable[[], object]] = [answer, empty]
            callbacks.append(factory())
            mapping: dict[str, Callable[[], object]] = {"answer": answer}
            gc_collect()
            assert callback is answer
            assert id(callback) == id(answer)
            assert holder.callback is callback
            assert holder.callback == callback
            assert not (holder.callback != callback)
            assert other()() is answer
            assert optional(False) is None
            assert optional(True) is answer
            present = optional(True)
            if present is not None:
                assert repr(present()) == "42"
            else:
                raise AssertionError("callback missing")
            return repr((first, callback(), consume(answer), consume_number(answer), holder.callback(), other()()(),
                         callbacks[0](), callbacks[1](), callbacks[2](), mapping["answer"]()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_adapters_retain_captures_and_unwind_callback_failures(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, values: list[int]):
                self.values = values

            def read(self, fail: bool) -> list[int]:
                gc_collect()
                if fail:
                    raise ValueError("read failed")
                return self.values

        def factory() -> Callable[[bool], object]:
            return Box([42] * 64).read

        def capture(values: list[int]) -> Callable[[], list[int]]:
            return lambda: values

        def captured() -> Callable[[], object]:
            return capture([7] * 64)

        def rebound() -> Callable[[], Callable[[bool], object]]:
            return lambda: Box([11] * 64).read

        def main() -> str:
            gc_set_threshold(1)
            callback = factory()
            retained = captured()
            create = rebound()
            deferred = create()
            value = callback(False)
            results: list[str] = []
            for fail in [True, False, True, False]:
                saved = value
                try:
                    value = callback(fail)
                except ValueError as error:
                    results.append(str(error))
                    results.append(str(value is saved))
                gc_collect()
                results.append(repr(value))
            return repr((results, retained(), deferred(False)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_adapter_allocation_failures_preserve_previous_binding(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Callable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def answer() -> int:
            return 42

        def factory() -> Callable[[], object]:
            return answer

        def main() -> int:
            callback = factory()
            value = callback()
            for mode in range(2):
                saved = callback
                old = value
                caught = False
                arm(1)
                try:
                    if mode == 0:
                        callback = factory()
                    else:
                        value = callback()
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or callback is not saved or value is not old:
                    return 1
                if repr(callback()) != "42":
                    return 2
            callback = factory()
            gc_collect()
            return 0 if repr(callback()) == "42" else 3
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


def test_callable_adapter_cannot_reinterpret_nested_mutable_storage():
    with pytest.raises(LLVMUnsupported, match="matching parameter and result types"):
        transpile_llvm('''
            from collections.abc import Callable
            def answer() -> int:
                return 42
            def widen(values: list[Callable[[], int]]) -> list[Callable[[], object]]:
                return values
            def main() -> str:
                return repr(widen([answer])[0]())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("actual", "selected", "value"), [
    ("int", "int | str", "42"),
    ("None", "int | None", "None"),
    ("str | None", "object", "'hello' if present else None"),
    ("int | str", "object", "42 if present else 'hello'"),
    ("list[int]", "object", "[42]"),
    ("bool", "object", "present"),
])
def test_callable_return_transport(tmp_path, optimize, actual, selected, value):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def read(present: bool) -> {actual}:
            gc_collect()
            return {value}
        def factory() -> Callable[[bool], {selected}]:
            return read
        def main() -> str:
            gc_set_threshold(1)
            callback = factory()
            gc_collect()
            return repr(callback(True)) + ':' + repr(callback(False))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_adapter_parameters_keep_semantic_and_numeric_storage(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def read(value: object, items: list[int], small: int8, real: float32) -> str:
            gc_collect()
            return repr(value) + repr(items) + str(small + int8(1)) + str(real)

        def make() -> Callable[[object, list[int], int8, float32], object]:
            return read

        def main() -> str:
            gc_set_threshold(1)
            callback = make()
            return repr(callback([1, 2], [3, 4], int8(127), float32(1.25)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_multiple_argument_and_item_adapters_are_independently_rooted(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value
            def read(self) -> int:
                gc_collect()
                return self.value

        def combine(a: Callable[[], object], b: Callable[[], object], c: Callable[[], object]) -> str:
            gc_collect()
            return repr((a(), b(), c()))

        def main() -> str:
            gc_set_threshold(1)
            indirect: Callable[[Callable[[], object], Callable[[], object], Callable[[], object]], str] = combine
            output = indirect(Box(1).read, Box(2).read, Box(3).read)
            output += combine(Box(4).read, Box(5).read, Box(6).read)
            callbacks: list[Callable[[], object]] = [Box(7).read, Box(8).read, Box(9).read]
            for callback in callbacks:
                output += repr(callback())
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("actual", "selected", "value"), [
    ("int", "float", "42"),
    ("bool", "int", "True"),
    ("bool", "int | None", "True"),
])
def test_callable_annotations_do_not_cast_numeric_results(actual, selected, value):
    with pytest.raises(LLVMUnsupported, match="explicit.*conversion"):
        transpile_llvm(f'''
            from collections.abc import Callable
            def answer() -> {actual}:
                return {value}
            def main() -> int:
                callback: Callable[[], {selected}] = answer
                callback()
                return 0
        ''')


def test_callable_result_adapter_cannot_erase_an_unboxed_callback():
    with pytest.raises(LLVMUnsupported, match="callable values require matching parameter and result types"):
        transpile_llvm('''
            from collections.abc import Callable
            def answer() -> int:
                return 42
            def nested() -> Callable[[], int]:
                return answer
            def main() -> str:
                callback: Callable[[], object] = nested
                return repr(callback())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_application_result_keeps_identity_and_dynamic_type(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, value: int):
                self.value = value
            def read(self) -> int:
                return self.value

        class Child(Base):
            def read(self) -> int:
                return self.value + 1

        def capture(value: Child) -> Callable[[], Child]:
            return lambda: value

        def widen(callback: Callable[[], Child]) -> Callable[[], Base]:
            return callback

        def erase(callback: Callable[[], Base]) -> Callable[[], object]:
            return callback

        def main() -> str:
            gc_set_threshold(1)
            value = Child(41)
            original = capture(value)
            callback = widen(original)
            erased = erase(callback)
            gc_collect()
            result = callback()
            opaque = erased()
            assert erased is original
            assert result is value
            assert opaque is value
            return repr((result.read(), isinstance(opaque, Child)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_adapter_exception_trace_contains_only_authored_frames(tmp_path):
    result = LLVM().run_source('''
        from collections.abc import Callable
        def fail() -> int:
            raise ValueError("callback failed")
        def main() -> str:
            callback: Callable[[], object] = fail
            return repr(callback())
    ''', filename="callback_trace.py", directory=tmp_path)
    assert result.returncode < 0
    assert result.stderr == (
        "Traceback (native PyJS):\n"
        '  File "callback_trace.py", line 7, in main\n'
        '  File "callback_trace.py", line 4, in fail\n'
        "ValueError: callback failed\n"
    )


def test_equivalent_callable_signatures_share_one_adapter(tmp_path):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        def first() -> int:
            return 1
        def second() -> int:
            return 2
        def main() -> str:
            a: Callable[[], object] = first
            b: Callable[[], object] = second
            c: Callable[[], object] = first
            assert a is c
            assert a is not b
            return repr((a(), b(), c()))
    ''', directory=tmp_path)
    # The complete module includes the managed runtime. Count only adapter
    # definitions: declaration-object identity must not duplicate one signature.
    source = (tmp_path / "program.ll").read_text()
    assert source.count("define ptr @pyjs.callable.adapt.") == 1
