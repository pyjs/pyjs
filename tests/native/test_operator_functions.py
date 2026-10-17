import ast
import inspect
import textwrap

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.decorators import js_metadata
from pyjs.native import operator as models
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("returned", ["other", "other if isinstance(other, str) else True"])
def test_operator_map_projects_selected_overload_results(tmp_path, optimize, returned):
    # The generated callback must keep the overload's bool/int runtime kind,
    # not impose an integer-only return ABI that the application never wrote.
    comparison = LLVM().assert_matches_python('''
import operator
from typing import overload
from pyjs.native import gc_collect, gc_set_threshold
class Value:
    @overload
    def __add__(self, other: int) -> int: ...
    @overload
    def __add__(self, other: str) -> str: ...
    def __add__(self, other: int | str) -> int | str:
        gc_collect()
        return RETURNED
def main() -> str:
    gc_set_threshold(1)
    values = [Value(), Value()]
    numbers = list(map(operator.add, values, [1, 2]))
    words = map(operator.add, values, ["a", "b"])
    gc_collect()
    result = ""
    for word in words:
        result += word
    return str(numbers) + "|" + result
'''.replace("RETURNED", returned), directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_operator_templates_consume_each_argument_once_in_the_expected_order():
    for function in vars(models).values():
        if js_metadata(function, "analysis") is not models._analyze_expression:
            continue
        node = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
        if isinstance(node.body[0], ast.AugAssign):
            assert len(node.body) == 2 and isinstance(node.body[1], ast.Return), function.__name__
            assert node.body[0].target.id == node.body[1].value.id, function.__name__
        elif isinstance(node.body[0], (ast.Assign, ast.Delete)):
            assert len(node.body) == 1 and len(node.body[0].targets) == 1, function.__name__
            assert isinstance(node.body[0].targets[0], ast.Subscript), function.__name__
        else:
            assert len(node.body) == 1 and isinstance(node.body[0], ast.Return), function.__name__
        parameters = list(inspect.signature(function).parameters)
        used = [child.id for child in ast.walk(node.body[0])
                if isinstance(child, ast.Name) and child.id in parameters]
        if isinstance(node.body[0], (ast.Assign, ast.Delete)):
            assert sorted(used) == sorted(parameters), function.__name__
        else:
            assert used == (parameters[::-1] if function is models.contains else parameters), function.__name__
        assert not any(isinstance(child, (ast.IfExp, ast.BoolOp)) for child in ast.walk(node.body[0]))


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_scalar_syntax_and_portable_results(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from operator import add as plus, inv, invert
        from pyjs import int8, int64, float32, uint32
        def main() -> str:
            empty: list[int] = []
            narrow: int8 = plus(int8(120), int8(10))
            big: int64 = op.mul(int64(9007199254740993), int64(3))
            single: float32 = op.truediv(float32(7), float32(2))
            return repr((narrow, big, single, op.abs(int8(-128)), op.neg(int8(-7)),
                         op.pos(True), op.neg(False), +True, -True, inv(2), invert(int8(2)),
                         op.add(2, 0.5), op.sub(7.5, 2.0), op.mul(6, 7),
                         op.truediv(7, 2), op.floordiv(-7, 3), op.mod(-7, 3),
                         op.floordiv(-7.5, 2.0), op.mod(-7.5, 2.0), op.pow(3, 4),
                         op.and_(7, 3), op.or_(4, 1), op.xor(7, 3),
                         op.lshift(int8(1), int8(7)), op.rshift(int8(-8), int8(2)),
                         op.eq(4, 4), op.ne(1, 2), op.ge(4.0, 5.0), op.le(2, 2),
                         op.lt(uint32(-1), uint32(1)), op.gt(5, 2),
                         op.not_(empty), op.truth([1]), op.is_none(None),
                         op.is_not_none(4), op.add(1, op.mul(2, op.add(3, 4)))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_contextual_callbacks_and_lazy_error_consumption(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from operator import mul as product
        from functools import reduce
        from itertools import accumulate, filterfalse, takewhile, dropwhile
        from pyjs import int8
        def main() -> str:
            pairs = list(map(op.truediv, [3.0, 5.0], [2.0, 4.0]))
            small = list(map(op.neg, [int8(-128), int8(2)]))
            running = list(accumulate([2, 3, 4], func=product, initial=1))
            results = (list(map(op.abs, [-3.5, 2.0])), pairs, small, running,
                       reduce(op.floordiv, [100, 5, 2]),
                       reduce(op.add, [2, 3], initial=10),
                       list(map(op.lt, [1, 3], [2, 2])),
                       list(filter(op.truth, [0, 2, 0, 3])),
                       list(filter(op.not_, [0.0, 2.0, 0.0])),
                       list(filterfalse(op.truth, [0, 2, 0])),
                       list(takewhile(op.truth, [1, 2, 0, 3])),
                       list(dropwhile(op.truth, [1, 2, 0, 3])))
            divisors = iter([2, 0, 5])
            cursor = map(op.floordiv, [10, 20, 30], divisors)
            first = next(cursor)
            message = ""
            try: next(cursor)
            except ZeroDivisionError as error: message = str(error)
            last = next(cursor)
            return repr((results, first, message, last))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_application_dispatch_results_and_gc(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from functools import reduce
        from itertools import accumulate
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int): self.value = value
            def __add__(self, other: "Value") -> "Value":
                gc_collect()
                return Value(self.value + other.value)
            def __eq__(self, other: "Value") -> bool:
                gc_collect()
                return self.value == other.value
            def __neg__(self) -> int:
                gc_collect()
                return -self.value
            def __truediv__(self, other: "Value") -> str:
                gc_collect()
                return str(self.value // other.value)
        class Shifted(Value):
            def __add__(self, other: Value) -> Value:
                gc_collect()
                return Value(self.value + other.value + 10)
        class Left:
            pass
        class Right:
            def __radd__(self, other: Left) -> str:
                gc_collect()
                return "reflected"
            def __gt__(self, other: Left) -> bool: return True
        def combine(left: Value, right: Value) -> Value:
            return op.add(left, right)
        def main() -> str:
            gc_set_threshold(1)
            left: list[Value] = [Value(1), Shifted(2)]
            right: list[Value] = [Value(3), Value(4)]
            marker = Left()
            values = (combine(Shifted(2), Value(3)).value,
                      [item.value for item in map(op.add, left, right)],
                      list(map(op.eq, left, right)), reduce(op.add, left).value,
                      [item.value for item in accumulate(left, op.add)],
                      list(map(op.neg, left)), op.truediv(Value(8), Value(2)).zfill(2),
                      op.add(Left(), Right()).upper(), op.lt(Left(), Right()),
                      op.eq(marker, marker), op.ne(marker, Left()))
            gc_collect()
            return repr(values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_arguments_bind_in_call_order_before_protocols(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from pyjs.native import gc_collect, gc_set_threshold
        class Bag:
            def __init__(self, events: list[int]): self.events = events
            def __contains__(self, value: int) -> bool:
                gc_collect()
                self.events.append(3)
                return value == 7
            def __getitem__(self, value: int) -> int:
                gc_collect()
                self.events.append(4)
                return value + 10
        def container(events: list[int]) -> Bag:
            events.append(1)
            return Bag(events)
        def item(events: list[int], fail: bool = False) -> int:
            gc_collect()
            events.append(2)
            if fail: raise ValueError("argument")
            return 7
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = op.contains(container(events), item(events))
            second = op.getitem(container(events), item(events))
            try: op.contains(container(events), item(events, True))
            except ValueError: events.append(5)
            return repr((first, second, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_collection_identity_and_checked_errors(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        class Marker: pass
        def main() -> str:
            values = [3, 5, 8]
            names = {"first": "Ada"}
            first = Marker()
            second = Marker()
            optional: Marker | None = first
            result = (op.getitem(values, -1), op.getitem(names, "first"),
                      op.getitem(("zero", 1, 2.5), 1), op.getitem("native", 2),
                      op.contains(values, 5), op.contains(names, "first"),
                      op.contains({2, 4}, 3), op.contains("taskmaster", "master"),
                      op.is_(first, first), op.is_not(first, second),
                      op.is_none(optional), op.is_not_none(optional))
            errors: list[str] = []
            try: op.getitem(values, 20)
            except IndexError as error: errors.append(str(error))
            try: op.getitem(names, "absent")
            except KeyError as error: errors.append(str(error))
            try: op.truediv(1.0, 0.0)
            except ZeroDivisionError as error: errors.append(str(error))
            try: op.lshift(1, -1)
            except ValueError as error: errors.append(str(error))
            return repr((result, errors, values, names))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["op.add(1)", "op.neg(1, 2)", "op.add(left=1, right=2)",
                                        "op.add(*(1, 2))", "list(map(op.neg, [1], [2]))"])
def test_operator_invalid_calls_have_structured_diagnostics(expression):
    with pytest.raises(CompilationError) as caught:
        transpile_llvm(f"import operator as op\ndef main() -> object:\n    return {expression}\n",
                       filename="operator_contract.py")
    assert caught.value.lineno == 3


@pytest.mark.parametrize("expression, message", [
    ("list(map(op.add, [1]))", "operator.add takes 2 arguments, but map supplies 1"),
    ("list(map(op.neg, [1], [2]))", "operator.neg takes 1 argument, but map supplies 2"),
    ("list(filter(op.add, [1]))", "operator.add takes 2 arguments, but filter supplies 1"),
])
def test_operator_callback_arity_diagnostic_names_the_source_function(expression, message):
    with pytest.raises(CompilationError) as caught:
        transpile_llvm(f"import operator as op\ndef main() -> object:\n    return {expression}\n",
                       filename="operator_callback.py")
    assert caught.value.lineno == 3
    assert message in str(caught.value)
    assert "Lambda" not in str(caught.value)


def test_operator_map_missing_iterable_names_the_missing_argument():
    with pytest.raises(CompilationError) as caught:
        transpile_llvm("import operator as op\ndef main() -> object:\n    return list(map(op.neg))\n",
                       filename="operator_callback.py")
    assert caught.value.lineno == 3
    assert "map() requires at least one iterable" in str(caught.value)
    assert "supplies 0" not in str(caught.value)


@pytest.mark.parametrize("expression", ["op.copy", "op.ast", "op.adapt_callback", "op._expression"])
def test_operator_namespace_does_not_expose_compiler_helpers(expression):
    with pytest.raises(CompilationError) as caught:
        transpile_llvm(f"import operator as op\ndef main() -> object:\n    return {expression}\n",
                       filename="operator_namespace.py")
    assert caught.value.lineno == 3
    assert "PYJS1003" in str(caught.value)


def test_operator_unmodelled_import_keeps_a_located_diagnostic_when_used():
    with pytest.raises(CompilationError) as caught:
        transpile_llvm("from operator import length_hint\ndef main() -> object:\n    return length_hint([1])\n",
                       filename="operator_namespace.py")
    assert caught.value.lineno == 3
    assert "PYJS1004" in str(caught.value)


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_host_aliases_and_unused_unmodelled_imports(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from operator import __index__ as index, __add__ as add
        from operator import iadd, concat, setitem, methodcaller, itemgetter
        def main() -> str:
            return repr((index(7), op.__index__(8), list(map(index, [1, 2])),
                         list(map(op.__index__, [3, 4])), add(2, 3), op.__add__(4, 5),
                         list(map(add, [1, 2], [3, 4]))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_templates_do_not_capture_caller_names_or_drop_method_receivers(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        import operator as __pyjs_operator_1
        from operator import sub as subtract
        from operator import neg as __pyjs_operator_0
        def abs(value: int) -> int: return 999
        def _abs(value: int) -> int: return value + 100
        def bool(value: int) -> int: return 0
        class Callbacks:
            def neg(self, value: int) -> int: return value + 10
        def callbacks(events: list[int]) -> Callbacks:
            events.append(1)
            return Callbacks()
        def main() -> str:
            events: list[int] = []
            direct = op.abs(-7)
            nested = op.add(_abs(2), op.mul(3, op.add(4, 5)))
            mapped = list(map(callbacks(events).neg, [1, 2]))
            return repr((direct, abs(5), nested, mapped, events,
                         list(map(op.abs, [-3, 4])), list(filter(op.neg, [1, 0, 2])),
                         list(map(__pyjs_operator_0, [1, 2])),
                         list(map(__pyjs_operator_1.add, [1, 2], [3, 4])),
                         list(map(subtract, [5, 8], [2, 3]))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_callback_allocation_failures_preserve_inputs_and_recover(tmp_path, optimize):
    source = transpile_llvm('''
        import operator as op
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        class Value:
            def __init__(self, value: int): self.value = value
            def __add__(self, other: "Value") -> "Value":
                gc_collect()
                return Value(self.value + other.value)
            def __eq__(self, other: "Value") -> bool:
                gc_collect()
                return self.value == other.value
        def calculate(values: list[Value]) -> int:
            doubled = list(map(op.add, values, values))
            if not op.contains(values, Value(2)): return -1
            return op.add(doubled[0], doubled[1]).value
        def main() -> int:
            gc_set_threshold(1)
            values = [Value(1), Value(2)]
            caught = 0
            exhausted = False
            for stage in range(1, 200):
                result = -1
                try:
                    arm(stage)
                    result = calculate(values)
                    exhausted = remaining() > 0
                    arm(0)
                    assert result == 6
                except MemoryError:
                    arm(0)
                    caught += 1
                    assert result == -1
                finally:
                    arm(0)
                gc_collect()
                assert values[0].value == 1 and values[1].value == 2
                assert calculate(values) == 6
                if exhausted: break
            assert exhausted and caught > 0
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
