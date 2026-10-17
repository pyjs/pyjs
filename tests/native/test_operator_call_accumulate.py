import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_call_reuses_binding_and_preserves_callee_argument_order(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from collections.abc import Callable as Function
        from operator import call as invoke
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Callable:
            def __init__(self, events: list[str]): self.events = events
            def __call__(self, value: int, *, scale: int = 2) -> int:
                self.events.append("call")
                gc_collect()
                return value * scale
            def method(self, value: int) -> int:
                self.events.append("method")
                return value + 1
        def callee(events: list[str]) -> Callable:
            events.append("callee")
            gc_collect()
            return Callable(events)
        def argument(events: list[str], value: int) -> int:
            events.append(str(value))
            gc_collect()
            return value
        def combine(left: int, right: int, *, scale: int = 1) -> int:
            return (left + right) * scale
        def represented(value: int8) -> int8: return value + int8(1)
        def keyword_names(*, function: int, args: int, kwargs: int) -> int:
            return function + args + kwargs
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            direct = op.call(callee(events).__call__, argument(events, 3), scale=argument(events, 4))
            bound = invoke(callee(events).method, argument(events, 5))
            callback: Function[[int], int] = callee(events).method
            indirect = op.call(callback, argument(events, 7))
            items = [2, 5]
            options = {"scale": 6}
            packed = op.call(combine, *items, **options)
            created = invoke(Callable, events)
            return repr((direct, bound, indirect, packed, events,
                         invoke(op.call, combine, 2, 3), int(invoke(represented, int8(127))),
                         invoke(len, [1, 2]), invoke(int, "7"), created.method(9),
                         invoke(keyword_names, function=1, args=2, kwargs=3)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_accumulate_uses_application_addition_and_retains_totals(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import accumulate
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int, events: list[int]):
                self.value, self.events = value, events
            def __add__(self, other: "Value") -> "Value":
                self.events.append(other.value)
                gc_collect()
                if other.value == 99: raise ValueError("bad item")
                return Value(self.value + other.value, self.events)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = [Value(1, events), Value(2, events), Value(99, events), Value(4, events)]
            stream = accumulate(values)
            assert events == []
            first = next(stream)
            second = next(stream)
            try: next(stream)
            except ValueError as error: assert str(error) == "bad item"
            last = next(stream)
            assert next(stream, None) is None
            empty: list[Value] = []
            empty_count = len(list(accumulate(empty)))
            seeded = [value.value for value in accumulate(empty, initial=Value(10, events))]
            lists = list(accumulate([[1], [2], [3]]))
            represented = list(accumulate([[int8(127)], [int8(-128)]]))
            gc_collect()
            return repr((first.value, second.value, last.value, first is values[0],
                         events, empty_count, seeded, lists, represented))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_accumulate_explicit_none_keeps_keyword_order_and_exceptions(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import accumulate
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int): self.value = value
            def __add__(self, other: "Value") -> "Value":
                gc_collect()
                return Value(self.value + other.value)
        def values(events: list[str]) -> list[Value]:
            events.append("values")
            return [Value(1), Value(2)]
        def default(events: list[str], fail: bool) -> None:
            events.append("default")
            gc_collect()
            if fail: raise ValueError("default failed")
        def initial(events: list[str]) -> Value:
            events.append("initial")
            return Value(10)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            positional = list(accumulate(values(events), default(events, False), initial=initial(events)))
            keyword = list(accumulate(initial=initial(events), func=default(events, False), iterable=values(events)))
            try: accumulate(values(events), default(events, True), initial=initial(events))
            except ValueError: events.append("caught")
            return repr(([value.value for value in positional], [value.value for value in keyword], events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["op.call()", "op.call(function=target)", "op.call(*(target, 1))"])
def test_operator_call_requires_a_visible_positional_callee(expression):
    with pytest.raises(CompilationError, match="operator.call requires an explicit first positional callable") as caught:
        transpile_llvm(f'''import operator as op
def target(value: int) -> int: return value
def main() -> object:
    return {expression}
''', filename="operator_call.py")
    assert caught.value.lineno == 4


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_call_preserves_contextual_constructor_types(optimize):
    result = LLVM().assert_matches_python('''
        from operator import call
        def receive(values: list[int]) -> list[int]:
            values.append(127)
            return values
        def produce() -> dict[str, list[int]]:
            return call(call, dict)
        def main() -> str:
            values: list[int] = call(list)
            values.append(127)
            values[0] += 1
            nested: list[list[int]] = call(call, list)
            nested.append(values)
            mapping = produce()
            mapping["items"] = receive(call(list))
            keys: set[int] = call(set)
            keys.add(128)
            return repr((nested, mapping, sorted(keys)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["list()", "call(list)"])
def test_operator_call_keeps_direct_represented_empty_constructor_boundary(expression):
    with pytest.raises(CompilationError, match="incompatible nested representation"):
        transpile_llvm(f'''from operator import call
from pyjs import int8
def main() -> object:
    values: list[int8] = {expression}
    return values
''')


@pytest.mark.parametrize("name", ["int", "float", "str", "bytes"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_default_accumulate_uses_application_addition_for_builtin_namesakes(name, optimize):
    result = LLVM().assert_matches_python(f'''
        from builtins import int as Integer, str as Text
        from itertools import accumulate
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, value: Integer): self.value = value
            def __add__(self, other: "{name}") -> "{name}":
                gc_collect()
                return {name}(self.value + other.value)
        def main() -> Text:
            gc_set_threshold(1)
            return repr([value.value for value in accumulate([{name}(1), {name}(2), {name}(3)])])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_default_accumulate_diagnostic_retains_cause_and_explains_explicit_callback():
    with pytest.raises(CompilationError, match="Operator.*not supported") as caught:
        transpile_llvm('''from itertools import accumulate
def main() -> object:
    values: list[int | str] = [1, "two"]
    return list(accumulate(values))
''', filename="default_addition.py")
    diagnostic = caught.value.diagnostic
    assert caught.value.lineno == 4
    assert "While analyzing default accumulate addition (left + right)." in diagnostic.notes
    assert any("explicit typed func" in help_text for help_text in diagnostic.help)


@pytest.mark.parametrize("source, message", [
    ('''from collections.abc import Callable
def collect(callback: Callable[[int, int], int] | None) -> list[int]:
    return list(accumulate([1, 2], callback))
def main() -> object: return collect(None)
''', "matching two-argument callback and result representation"),
    ('''def collect(initial: int | None) -> list[int]:
    return list(accumulate([1, 2], initial=initial))
def main() -> object: return collect(None)
''', "initial must match the item type and representation"),
    ('''class Value:
    def __add__(self, other: "Value") -> int: return 1
def main() -> object: return list(accumulate([Value(), Value()]))
''', "matching two-argument callback and result representation"),
])
def test_accumulate_rejects_unresolved_optional_inputs_and_changing_result_types(source, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm("from itertools import accumulate\n" + source, filename="accumulate_contract.py")
    assert caught.value.lineno > 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_call_failures_preserve_evaluation_order_and_void_results(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Handler:
            def __init__(self, events: list[str]): self.events = events
            def handle(self, value: int) -> int:
                self.events.append("body")
                gc_collect()
                return value + 1
        def factory(events: list[str], fail: bool) -> Callable[[int], int]:
            events.append("factory")
            gc_collect()
            if fail: raise ValueError("factory")
            return Handler(events).handle
        def argument(events: list[str], fail: bool) -> int:
            events.append("argument")
            gc_collect()
            if fail: raise ValueError("argument")
            return 4
        def done(events: list[str]) -> None: events.append("done")
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            try: op.call(factory(events, True), argument(events, False))
            except ValueError: events.append("caught-factory")
            try: op.call(factory(events, False), argument(events, True))
            except ValueError: events.append("caught-argument")
            value = op.call(factory(events, False), argument(events, False))
            result = op.call(done, events)
            return repr((events, value, result))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_accumulate_keeps_reflected_dispatch_and_binary_not_inplace_semantics(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import accumulate
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int, events: list[str]):
                self.value, self.events = value, events
            def __add__(self, other: "Value") -> "Value":
                self.events.append("add")
                gc_collect()
                return Value(self.value + other.value, self.events)
            def __iadd__(self, other: "Value") -> "Value":
                raise ValueError("must not use inplace")
        class Child(Value):
            def __radd__(self, other: Value) -> Value:
                self.events.append("reflected")
                gc_collect()
                return Value(self.value * 10 + other.value, self.events)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values: list[Value] = [Value(1, events), Child(2, events), Value(3, events)]
            totals = list(accumulate(values))
            pieces = [[1], [2], [3]]
            lists = list(accumulate(pieces))
            gc_collect()
            return repr(([value.value for value in totals], events, pieces, lists,
                         lists[0] is pieces[0], lists[1] is lists[0]))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_accumulate_callback_allocation_failures_recover_through_operator_call(tmp_path, optimize):
    source = transpile_llvm('''
        from itertools import accumulate
        from operator import call
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        class Value:
            def __init__(self, value: int): self.value = value
            def __add__(self, other: "Value") -> "Value":
                gc_collect()
                return Value(self.value + other.value)
        def calculate(values: list[Value], initial: Value) -> list[int]:
            return [value.value for value in accumulate(values, None, initial=initial)]
        def main() -> int:
            gc_set_threshold(1)
            values = [Value(1), Value(2), Value(3)]
            initial = Value(10)
            failures = 0
            exhausted = False
            for stage in range(1, 200):
                try:
                    arm(stage)
                    result = call(calculate, values, initial)
                    exhausted = remaining() > 0
                    arm(0)
                    assert result == [10, 11, 13, 16]
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert [value.value for value in values] == [1, 2, 3] and initial.value == 10
                assert call(calculate, values, initial) == [10, 11, 13, 16]
                if exhausted: break
            assert exhausted and failures > 0
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
