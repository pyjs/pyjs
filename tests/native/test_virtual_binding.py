import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expanded", [False, True])
@pytest.mark.parametrize("receiver", ["Base", "Base | Other"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_selected_signatures_keep_widening_iterator_adapters(tmp_path, expanded, receiver, optimize):
    argument = "*(iter([1, 2]),)" if expanded else "iter([1, 2])"
    other = " + ':' + invoke(Other())" if "Other" in receiver else ""
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def read(self, value: Iterator[object]) -> str:
                gc_collect()
                return str(next(value)) + str(next(value))
        class Child(Base):
            def read(self, renamed: Iterator[object]) -> str:
                gc_collect()
                return str(next(renamed)) + str(next(renamed))
        class Other:
            def read(self, value: Iterator[object]) -> str:
                gc_collect()
                return str(next(value)) + str(next(value))
        def invoke(source: {receiver}) -> str:
            return source.read({argument})
        def main() -> str:
            gc_set_threshold(1)
            return invoke(Base()) + ':' + invoke(Child()){other}
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == ("12:12:12" if other else "12:12")
    assert result.native.stderr == ""


@pytest.mark.parametrize("annotation,value,message", [
    ("Iterable[int]", "[True]", "iterator views require an explicit numeric conversion"),
    ("Iterable[int]", "[K.X]", "scalar enums cannot be erased or widened"),
    ("tuple[Iterable[int], ...]", "values", "tuple views require matching concrete item storage"),
    ("list[Iterator[object]]", "cursors", "stored iterator views require matching item and send layouts"),
])
def test_selected_conversion_diagnostics_retain_underlying_storage_reason(annotation, value, message):
    with pytest.raises(LLVMUnsupported, match=message) as caught:
        transpile_llvm(f'''
            from collections.abc import Iterable, Iterator
            from enum import IntEnum
            class K(IntEnum): X = 1
            class Base:
                def read(self, value: {annotation}) -> int: return 1
            class Child(Base):
                def read(self, renamed: {annotation}) -> int: return 2
            def invoke(source: Base) -> int:
                values: tuple[list[int], ...] = ([1],)
                cursors = [iter([1])]
                return source.read({value})
            def main() -> int:
                return invoke(Base()) + invoke(Child())
        ''')
    assert caught.value.node is not None
    assert caught.value.node.lineno is not None
    assert any("Source location: _pyjs_native_.py:" in note and "(invoke;" in note
               for note in caught.value.__notes__)


@pytest.mark.parametrize("expanded", [False, True])
@pytest.mark.parametrize("receiver", ["Base", "Base | Other"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_selected_signatures_keep_structural_iterable_adapters(tmp_path, expanded, receiver, optimize):
    argument = "*([20, 22],)" if expanded else "[20, 22]"
    other = " + ':' + str(invoke(Other()))" if "Other" in receiver else ""
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterable
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def read(self, values: Iterable[int]) -> int:
                gc_collect()
                return sum(values) + sum(values)
        class Child(Base):
            def read(self, renamed: Iterable[int], extra: int = 1) -> int:
                gc_collect()
                return sum(renamed) + extra
        class Other:
            def read(self, values: Iterable[int]) -> int:
                gc_collect()
                return sum(values)
        def invoke(source: {receiver}) -> int:
            return source.read({argument})
        def main() -> str:
            gc_set_threshold(1)
            return str(invoke(Base())) + ':' + str(invoke(Child())){other}
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == ("84:43:42" if other else "84:43")
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_rejected_selected_call_still_links_reached_container_body(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Base:
            def read(self, original: str) -> str:
                return original
        class Child(Base):
            def read(self, renamed: list[int]) -> str:
                return str(renamed[0] + 1)
        def invoke(source: Base) -> str:
            try:
                return source.read('text')
            except TypeError:
                return 'checked'
        def optional(value: list[int] | None) -> int:
            if value is None:
                return 0
            return value[0] + 1
        def main() -> str:
            return invoke(Base()) + ':' + invoke(Child()) + ':' + str(optional(None))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "text:checked:0"
    assert result.native.stderr == ""


@pytest.mark.parametrize("annotation,value,converted", [
    ("float", "1", "float(1)"),
    ("int", "True", "int(True)"),
    ("int", "K.X", "int(K.X)"),
    ("float | None", "2", "float(2)"),
])
@pytest.mark.parametrize("dispatch", ["direct", "union", "virtual"])
def test_selected_calls_keep_explicit_conversion_diagnostics(tmp_path, annotation, value, converted, dispatch):
    base = "(A)" if dispatch != "union" else ""
    extra = ", extra: int = 0" if dispatch == "virtual" else ""
    receiver = "A" if dispatch != "union" else "A | B"
    call = "A().f(ARGUMENT)" if dispatch == "direct" else "source.f(ARGUMENT)"
    source = f'''
        from enum import IntEnum
        class K(IntEnum):
            X = 4
        class A:
            def f(self, value: {annotation}) -> str:
                return str(value)
        class B{base}:
            def f(self, value: {annotation}{extra}) -> str:
                return str(value)
        def invoke(source: {receiver}) -> str:
            try:
                return {call}
            except TypeError:
                return 'incorrect runtime failure'
        def main() -> str:
            return invoke(A()) + ':' + invoke(B())
    '''
    # Unsupported typing-valid numeric promotions must remain a compilation
    # diagnostic on every dispatch path, not a catchable semantic divergence.
    with pytest.raises(LLVMUnsupported, match="conversion|scalar enums|optional payload") as caught:
        transpile_llvm(source.replace("ARGUMENT", value))
    assert "expanded call" not in str(caught.value)
    result = LLVM().assert_matches_python(source.replace("ARGUMENT", converted),
        directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("shape,value,access,accepted", [
    ("tuple[{}]", "(More(7),)", "[0].number", True),
    ("tuple[{}, ...]", "(More(7),)", "[0].number", True),
    ("tuple[tuple[{}]]", "((More(7),),)", "[0][0].number", True),
    ("list[tuple[{}]]", "[(More(7),)]", "[0][0].number", False),
])
@pytest.mark.parametrize("expanded", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_selected_tuple_upcasts_preserve_mutable_invariance(tmp_path, shape, value, access, accepted, expanded, optimize):
    argument = "*(value,)" if expanded else "value"
    source = f'''
        class Item:
            def __init__(self, number: int):
                self.number = number
        class More(Item):
            pass
        class Base:
            def read(self, value: {shape.format('Item')}) -> str:
                return str(value{access})
        class Child(Base):
            def read(self, renamed: {shape.format('Item')}) -> str:
                return str(renamed{access})
        def invoke(source: Base, value: {shape.format('More')}) -> str:
            try:
                return source.read({argument})
            except TypeError:
                return 'checked'
        def main() -> str:
            values: {shape.format('More')} = {value}
            return invoke(Base(), values) + ':' + invoke(Child(), values)
    '''
    if not accepted and not expanded:
        with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
            transpile_llvm(source)
        return
    result = LLVM().compare_with_python(source, directory=tmp_path, optimize=optimize,
                                        sanitizers=("address", "undefined"))
    assert result.python.returncode == result.native.returncode == 0
    assert result.python.stdout == "7:7"
    assert result.native.stdout == ("7:7" if accepted else "checked:checked")
    assert result.python.stderr == result.native.stderr == ""


@pytest.mark.parametrize("actual,expected,value,retry", [
    ("A", "B", "A()", "B()"),
    ("int", "str", "42", "'retry'"),
    ("list[A]", "list[B]", "[A()]", "[B()]"),
    ("str", "list[int]", "'text'", "[7]"),
    ("str | None", "str", "None", "'retry'"),
    ("int8", "int16", "int8(42)", "int16(7)"),
])
@pytest.mark.parametrize("form", ["fixed", "args", "kwargs"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_selected_arguments_reject_incompatible_storage(tmp_path, actual, expected, value, retry, form, optimize):
    prefix = {"fixed": "", "args": "*", "kwargs": "**"}[form]
    tail = "*, tail: int = 0" if form == "fixed" else "tail: int = 0"
    base_params = f"{prefix}original: {actual}, {tail}"
    child_params = f"{prefix}renamed: {expected}, {tail}"
    if form == "kwargs":
        base_params = f"tail: int = 0, **original: {actual}"
        child_params = f"tail: int = 0, **renamed: {expected}"
    argument = "item=" if form == "kwargs" else ""
    source = f'''
        from pyjs import int8, int16
        from pyjs.native import gc_collect, gc_set_threshold
        events: list[str] = []
        class A:
            def __init__(self):
                self.value = 'hello'
        class B:
            def __init__(self):
                self.value = 7
        class Base:
            def read(self, {base_params}) -> str:
                events.append('base')
                return 'base'
        class Child(Base):
            def read(self, {child_params}) -> str:
                events.append('child')
                return 'child'
        def value() -> {actual}:
            events.append('value')
            gc_collect()
            return {value}
        def tick() -> int:
            events.append('tick')
            gc_collect()
            return 1
        def invoke(source: Base) -> str:
            try:
                return source.read({argument}value(), tail=tick())
            except TypeError:
                return 'checked'
        def main() -> str:
            gc_set_threshold(1)
            first = invoke(Base())
            second = invoke(Child())
            third = Child().read({argument}{retry})
            return first + ':' + second + ':' + third + ':' + ','.join(events)
    '''
    if form == "fixed" and actual == "int8":
        # Shared analysis already rejects fixed represented parameter changes;
        # native binding additionally checks independently typed pack members.
        with pytest.raises(CompilationError, match="changes the represented storage contract"):
            transpile_llvm(source)
        return
    comparison = LLVM().compare_with_python(source, directory=tmp_path, optimize=optimize,
                                            sanitizers=("address", "undefined"))
    # CPython ignores annotations; the native typed boundary must reject the
    # selected incompatible arm without entering it or losing caller effects.
    assert comparison.python.returncode == comparison.native.returncode == 0
    assert comparison.python.stdout == "base:child:child:value,tick,base,value,tick,child,child"
    assert comparison.native.stdout == "base:checked:child:value,tick,base,value,tick,child"
    assert comparison.python.stderr == comparison.native.stderr == ""


@pytest.mark.parametrize("annotation,value", [
    ("int", "42"), ("str", "'child'"), ("bytes", "b'child'"),
    ("list[int]", "[1, 2]"), ("tuple[int, str]", "(1, 'x')"), ("None", "None"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_covariant_object_results_box_the_selected_body(tmp_path, annotation, value, optimize):
    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def make(self) -> object:
                return None
        class Child(Base):
            def make(self) -> {annotation}:
                gc_collect()
                return {value}
        def collect(value: Base) -> str:
            callback = value.make
            first = value.make()
            gc_collect()
            second = callback()
            gc_collect()
            return repr([first, second])
        def main() -> str:
            gc_set_threshold(1)
            return collect(Child())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("method,returns,body", [
    ("__iter__", "Base", "self"),
    ("__next__", "int", "42"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_protocol_consumers_bind_selected_required_arguments(tmp_path, method, returns, body, optimize):
    protocol = "iter" if method == "__iter__" else "next"
    comparison = LLVM().assert_matches_python(f'''
        class Base:
            def __iter__(self) -> Base:
                return self
            def __next__(self) -> int:
                return 1

        class Child(Base):
            def {method}(self, required: int) -> {returns}:
                return {body}

        def consume(value: Base) -> str:
            try:
                {protocol}(value)
            except TypeError:
                return "caught"
            return "missed"

        def main() -> str:
            child = Child()
            first = consume(child)
            child.{method}(42)
            return first + consume(child)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "caughtcaught"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_callbacks_select_override_defaults(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import starmap
        from pyjs.native import gc_collect, gc_set_threshold

        def record(value: int, extra: int, history: list[int]) -> int:
            history.append(value)
            gc_collect()
            if value < 0:
                raise ValueError("negative")
            return sum(history) + extra

        class Base:
            def make(self, value: int, extra: int = 1, *, history: list[int] = [10]) -> object:
                return record(value, extra, history)

            def key(self, value: int, direction: int = 1) -> int:
                return value * direction

        class Child(Base):
            def make(self, value: int, extra: int = 2, *, history: list[int] = [20]) -> int:
                return record(value, extra, history)

            def key(self, value: int, direction: int = -1) -> int:
                return value * direction

        class Text(Base):
            def make(self, value: int, extra: int = 3, *, history: list[int] = [30]) -> str:
                return "text:" + str(record(value, extra, history))

        class Inherited(Child):
            pass

        def pending(source: Base) -> Iterator[object]:
            return map(source.make, [1, -1, 2])

        def main() -> str:
            gc_set_threshold(1)
            result: list[object] = []
            sources: list[Base] = [Base(), Child(), Text(), Inherited()]
            for source in sources:
                values = pending(source)
                gc_collect()
                result.append(next(values))
                try:
                    next(values)
                except ValueError:
                    result.append("failed")
                result.append(next(values))
                result.extend(starmap(source.make, [(3, 100)]))
                result.append(sorted([1, 3, 2], key=source.key))
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == (
        "[12, 'failed', 13, 115, [1, 2, 3], 23, 'failed', 24, 125, [3, 2, 1], "
        "'text:34', 'failed', 'text:35', 'text:135', [1, 2, 3], "
        "28, 'failed', 29, 130, [3, 2, 1]]"
    )


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("separator", ["", "*, "])
def test_virtual_required_arguments_raise_and_recover(tmp_path, optimize, separator):
    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self):
                self.calls = 0

            def value(self, number: int, {separator}extra: int = 1) -> int:
                self.calls += 1
                return number + extra

        class Child(Base):
            def value(self, number: int, {separator}extra: int) -> int:
                self.calls += 1
                gc_collect()
                return number + extra

        def collect(source: Base) -> list[int]:
            result: list[int] = []
            values = map(source.value, [3, 4])
            for index in range(2):
                try:
                    result.append(next(values))
                except TypeError:
                    result.append(-1)
            try:
                result.append(source.value(6))
            except TypeError:
                result.append(-1)
            gc_collect()
            result.append(source.value(5, extra=2))
            result.append(source.calls)
            return result

        def main() -> str:
            gc_set_threshold(1)
            return str(collect(Base())) + str(collect(Child()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == "[4, 5, 7, 7, 4][-1, -1, -1, 7, 1]"


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("parameters,extra_type", [
    ("value: int, renamed: int = 2, last: int = 3", "int"),
    ("extra: int, value: int = 2, last: int = 3", "int"),
    ("extra: int, value: str = 'two', last: int = 3", "str"),
])
@pytest.mark.parametrize("expanded", [False, True])
def test_virtual_invalid_keywords_evaluate_all_arguments_before_raising(tmp_path, optimize, parameters, extra_type, expanded):
    def invocation(first, fail=False):
        argument = f"argument({first}, events)"
        extra = f"{extra_type}(argument({first + 1}, events))"
        last = f"argument({first + 2}, events, {fail!r})"
        if expanded:
            return f'source.value(*({argument},), **{{"extra": {extra}, "last": {last}}})'
        return f"source.value({argument}, extra={extra}, last={last})"

    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect

        class Base:
            def __init__(self, events: list[int]):
                self.events = events

            def value(self, value: int, extra: {extra_type} = {repr('one') if extra_type == 'str' else 1}, last: int = 2) -> int:
                return value + last

        class Child(Base):
            def value(self, {parameters}) -> int:
                self.events.append(99)
                return 42

        def argument(value: int, events: list[int], fail: bool = False) -> int:
            events.append(value)
            gc_collect()
            if fail:
                raise LookupError("argument failure")
            return value

        def call(source: Base, events: list[int]) -> int:
            try:
                {invocation(1)}
            except TypeError:
                events.append(-1)
            try:
                {invocation(4, True)}
            except LookupError:
                events.append(-2)
            gc_collect()
            return source.value(4)

        def main() -> str:
            events: list[int] = []
            result = call(Child(events), events)
            return str(events) + ":" + str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == "[1, 2, 3, -1, 4, 5, 6, -2, 99]:42"


@pytest.mark.parametrize("inheritance,receiver_type", [("(Base)", "Base"), ("", "Base | Child")])
def test_uncaught_virtual_binding_error_has_native_traceback(tmp_path, inheritance, receiver_type):
    comparison = LLVM().compare_with_python(f'''
        class Base:
            def value(self, extra: int = 1) -> int:
                return extra

        class Child{inheritance}:
            def value(self, extra: int) -> int:
                return extra

        def call(source: {receiver_type}) -> int:
            return source.value()

        def main() -> int:
            return call(Child())
    ''', directory=tmp_path)
    assert comparison.python.returncode == 1
    # Standalone native executables currently report uncaught errors then trap.
    assert comparison.native.returncode != 0
    assert "TypeError: missing required argument" in comparison.native.stderr
    assert "in call" in comparison.native.stderr
    assert "in main" in comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_binding_errors_recover_in_selected_method(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Optional:
            def value(self, extra: int = 1) -> int:
                return extra

        class Required:
            def value(self, extra: int) -> int:
                return extra

        def call(source: Optional | Required) -> int:
            try:
                return source.value()
            except TypeError:
                gc_collect()
                return source.value(7)

        def main() -> str:
            return str([call(Optional()), call(Required())])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == "[1, 7]"


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_direct_defaults_preserve_evaluation_and_super_binding(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def value(self, number: int, extra: int = -1, *, scale: float = +0.5) -> float:
                gc_collect()
                return (number + extra) * scale

            def touch(self, events: list[int], value: int = 1) -> None:
                events.append(value)

        class Child(Base):
            def value(self, number: int, extra: int = -2, *, scale: float = -0.5) -> float:
                return super().value(number, extra, scale=scale) + super().value(number)

            def touch(self, events: list[int], value: int = 2) -> None:
                gc_collect()
                super().touch(events, value)

        def receiver(events: list[int]) -> Base:
            events.append(10)
            return Child()

        def argument(value: int, events: list[int]) -> int:
            events.append(value)
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = receiver(events).value(argument(3, events))
            second = receiver(events).value(number=argument(4, events))
            third = receiver(events).value(argument(5, events), extra=argument(20, events))
            fourth = receiver(events).value(argument(6, events), **{"extra": argument(30, events)})
            fifth = receiver(events).value(*(argument(7, events),), scale=0.25)
            receiver(events).touch(events)
            return str([first, second, third, fourth, fifth]) + str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.returncode == 0
    assert comparison.native.stdout.strip() == (
        "[0.5, 0.5, -10.5, -15.5, 4.25][10, 3, 10, 4, 10, 5, 20, 10, 6, 30, 10, 7, 10, 2]"
    )


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("fail_at,retry_sum", [(1, 32), (2, 32), (3, 33), (4, 33)])
def test_virtual_default_allocation_failure_preserves_override_state(tmp_path, optimize, fail_at, retry_sum):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        class Base:
            def record(self, value: int, state: list[int] = [100]) -> int:
                return -1

        class Child(Base):
            def record(self, value: int, state: list[int] = [10, 20]) -> int:
                state.append(value)
                gc_collect()
                return sum(list(state))

        def check(source: Base) -> int:
            values = map(source.record, [1, 2, 3])
            caught = False
            arm({fail_at})
            try:
                next(values)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught:
                return 1
            if next(values) != {retry_sum}:
                return 2
            if source.record(4) != {retry_sum + 4}:
                return 3
            if next(values) != {retry_sum + 7}:
                return 4
            return 0

        def main() -> int:
            return check(Child())
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("fail_at,retry_sum", [(1, 32), (2, 32), (3, 33), (4, 33)])
@pytest.mark.parametrize("callback", ["record", "partial(record)", "lambda value: record(value)"])
def test_callback_default_allocation_failure_leaves_retryable_shared_state(tmp_path, optimize, fail_at, retry_sum, callback):
    # Header/backing failures leave the default unpublished. The third
    # and fourth allocations copy after append; that mutation must survive.
    # Scalar sum no longer allocates, so make the post-mutation boundary explicit.
    source = transpile_llvm(f'''
        from functools import partial
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def record(value: int, state: list[int] = [10, 20]) -> int:
            state.append(value)
            gc_collect()
            return sum(list(state))

        def main() -> int:
            values = map({callback}, [1, 2, 3])
            caught = False
            arm({fail_at})
            try:
                next(values)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught:
                return 1
            if next(values) != {retry_sum}:
                return 2
            if record(4) != {retry_sum + 4}:
                return 3
            if next(values) != {retry_sum + 7}:
                return 4
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
