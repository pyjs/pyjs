"""Callability is a type-slot query, never an attempted invocation."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_invoking_callable_values_does_not_invoke_the_callable_predicate(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def argument(events: list[int], value: int) -> int:
            events.append(value)
            gc_collect()
            return value
        def factory(events: list[int], fail: bool) -> Callable[[], str]:
            events.append(10)
            if fail: raise ValueError("factory")
            return lambda: str(events)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            zero = (lambda: "zero")()
            one = (lambda value: str(value))(argument(events, 1))
            two = (lambda a, b: repr((a, b)))(argument(events, 2), argument(events, 3))
            returned = factory(events, False)()
            callbacks: list[Callable[[], str]] = [lambda: "indexed"]
            indexed = callbacks[0]()
            try:
                factory(events, True)()
            except ValueError as error:
                events.append(len(str(error)))
            return repr((zero, one, two, returned, indexed, events, callable(factory),
                         callable(lambda: 1), callable(7)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_static_shapes_and_once_only_evaluation(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_set_threshold
        class Action:
            def __call__(self) -> int: return 1
            def run(self) -> int: return 2
        class ChildAction(Action): pass
        class Passive: pass
        def function() -> int: return 3
        def number() -> int:
            print("number")
            return 4
        def main() -> str:
            gc_set_threshold(1)
            action = Action()
            return str((callable(Action), callable(action), callable(action.run),
                callable(ChildAction()), callable(Passive()), callable(function),
                callable(lambda: 5), callable(1), callable(None), callable(number())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == (
        "number\n(True, True, True, True, False, True, True, False, False, False)")
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_polymorphic_optional_union_and_erased_values(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Base: pass
        class Action(Base):
            def __call__(self, value: int) -> int: return value + 1
        class Other(Base): pass
        class Leaf:
            def __call__(self) -> int: return 9
        def nominal(value: Base) -> bool: return callable(value)
        def optional(value: Base | None) -> bool: return callable(value)
        def union(value: Base | int | str) -> bool: return callable(value)
        def erased(value: object) -> bool:
            gc_collect()
            return callable(value)
        def callback(value: Callable[[int], int] | None) -> bool:
            gc_collect()
            return callable(value)
        def main() -> str:
            gc_set_threshold(1)
            action = Action()
            plain = Other()
            return repr((nominal(action), nominal(plain), optional(action),
                optional(plain), optional(None), union(action), union(plain),
                union(0), union("x"), erased(action), erased(plain), erased(None),
                erased(3), erased("s"), erased([1]), callback(action.__call__),
                callback(None), erased(Leaf())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_imports_shadowing_and_receiver_errors(optimize):
    result = LLVM().assert_matches_python('''
        import builtins
        from builtins import callable as query
        from collections.abc import Callable
        class Item:
            def method(self) -> int: return 4
        def receiver(events: list[int], fail: bool) -> Item:
            events.append(1)
            if fail: raise ValueError("receiver")
            return Item()
        def factory(events: list[int]) -> Callable[[], int]:
            events.append(2)
            return lambda: 9
        def shadow(callable: Callable[[int], bool]) -> bool:
            return callable(5)
        def main() -> str:
            events: list[int] = []
            first = query(receiver(events, False).method)
            second = builtins.callable(factory(events))
            try:
                query(receiver(events, True).method)
            except ValueError as error:
                events.append(len(str(error)))
            return repr((first, second, shadow(lambda value: value == 0), events,
                         query(int), query(len), query(builtins.len), query(builtins.int),
                         query(builtins.callable),
                         builtins.callable(Item)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_checks_slots_without_invoking_properties_or_bodies(optimize):
    result = LLVM().assert_matches_python('''
        class Property:
            @property
            def __call__(self) -> int:
                raise ValueError("must not run")
        class Disabled:
            __call__ = None
        class InstanceOnly:
            def __init__(self): self.__call__ = 3
        class Inherited(Property): pass
        def main() -> str:
            return repr((callable(Property()), callable(Disabled()),
                         callable(InstanceOnly()), callable(Inherited())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "(True, True, False, True)"
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_property_result_and_indexed_callback_evaluate_once(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self): self.events = 0
            @property
            def value(self) -> int:
                self.events += 1
                gc_collect()
                return 7
            @property
            def callback(self) -> Callable[[], int]:
                self.events += 10
                gc_collect()
                return lambda: 9
        def index(item: Item) -> int:
            item.events += 100
            return 0
        def main() -> str:
            gc_set_threshold(1)
            item = Item()
            values: list[Callable[[], int] | None] = [lambda: 1, None]
            first = callable(item.value)
            second = callable(item.callback)
            third = callable(values[index(item)])
            try:
                callable(values[3])
            except IndexError:
                item.events += 1000
            return repr((first, second, third, callable(values[1]), item.events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "(False, True, True, False, 1111)"
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "callable()", "callable(1, 2)", "callable(value=1)", "callable(*(1,))",
])
def test_callable_requires_one_positional_subject(expression):
    with pytest.raises(CompilationError, match=r"callable\(\) requires one positional subject"):
        transpile_llvm(f"def main() -> int:\n    return int({expression})\n")


@pytest.mark.parametrize("view", ["Iterable[int]", "Iterator[int]", "Generator[int, None, None]"])
def test_callable_does_not_guess_concrete_identity_through_iteration_views(view):
    with pytest.raises(CompilationError, match="require a concrete value"):
        transpile_llvm(f'''
            from collections.abc import Iterable, Iterator, Generator
            def query(value: {view}) -> bool: return callable(value)
            def main() -> int: return int(query(iter([1])))
        ''')


def test_callable_does_not_guess_mapped_dom_call_slots():
    with pytest.raises(CompilationError, match="cannot recover mapped DOM call slots"):
        transpile_llvm('''
            from pyjs.web.dom import Element
            def main(value: Element) -> int: return int(callable(value))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_builtin_declarations_and_concrete_noncallables(optimize):
    result = LLVM().assert_matches_python('''
        def main() -> str:
            return repr((callable(int), callable(str), callable(list), callable(dict),
                callable(set), callable(tuple), callable(bool), callable(object),
                callable(True), callable(1.5), callable("a"), callable(b"a"),
                callable([1]), callable({"x": 2}), callable({1}),
                callable((1, 2)), callable(range(3))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, initial", [("Callable[[], int]", "run"), ("Item", "Item()")])
@pytest.mark.parametrize("deferred", ["lambda: callable(value)", "(callable(value) for _ in range(2))"])
def test_callable_deferred_queries_observe_current_optional_storage(optimize, annotation, initial, deferred):
    invoke = "query()" if deferred.startswith("lambda") else "next(query)"
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __call__(self) -> int: return 1
        def run() -> int: return 1
        def main() -> str:
            gc_set_threshold(1)
            value: {annotation} | None = {initial}
            assert value is not None
            query = {deferred}
            before = {invoke}
            value = None
            gc_collect()
            return repr((before, {invoke}))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "(True, False)"
    assert not result.native.stderr


@pytest.mark.parametrize("backend", ["llvm", "jvm", "webassembly"])
def test_callable_query_helper_is_not_a_python_builtin(backend):
    from pyjs.java import transpile_jvm
    from pyjs.webassembly import transpile_webassembly
    compiler = {"llvm": transpile_llvm, "jvm": transpile_jvm, "webassembly": transpile_webassembly}[backend]
    with pytest.raises(CompilationError, match="Name 'is_callable' is not defined") as caught:
        compiler("def main() -> int:\n    return int(is_callable(1))\n", filename="query_scope.py")
    assert caught.value.filename == "query_scope.py"
    assert caught.value.lineno == 2


@pytest.mark.parametrize("expression", ["Action.run", "Action.build", "values.append", "'x'.upper"])
def test_callable_method_queries_keep_function_value_boundaries(expression):
    with pytest.raises(LLVMUnsupported, match="LLVM (method values require a bound receiver|function values require)"):
        transpile_llvm(f'''
            class Action:
                def run(self) -> int: return 1
                @classmethod
                def build(cls) -> int: return 1
            def main() -> int:
                values = [1]
                return int(callable({expression}))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Action | Passive", "Base", "object"])
@pytest.mark.parametrize("deferred", ["lambda", "generator"])
def test_deferred_guards_read_current_union_nominal_and_erased_storage(optimize, annotation, deferred):
    checks = ("(callable(value), isinstance(value, Action), bool(value), not value, "
              "value is None, bool(value and True), bool(value or False))")
    expression = f"lambda: {checks}" if deferred == "lambda" else f"({checks} for _ in range(3))"
    invoke = "query()" if deferred == "lambda" else "next(query)"
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __bool__(self) -> bool: return False
        class Action(Base):
            def __call__(self) -> int: return 1
            def __bool__(self) -> bool: return True
        class Passive(Base): pass
        def main() -> str:
            gc_set_threshold(1)
            value: {annotation} = Action()
            assert isinstance(value, Action)
            query = {expression}
            first = {invoke}
            value = Passive()
            gc_collect()
            second = {invoke}
            value = Action()
            gc_collect()
            return repr((first, second, {invoke}))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_deferred_payload_reads_still_check_a_stale_union_proof(optimize):
    result = LLVM().assert_matches_python('''
        class Action:
            def __init__(self): self.amount = 7
        class Passive: pass
        def main() -> str:
            value: Action | Passive = Action()
            assert isinstance(value, Action)
            read = lambda: value.amount + 1
            before = read()
            value = Passive()
            try:
                read()
            except Exception:
                return repr((before, "safe failure"))
            return "unchecked payload"
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "(8, 'safe failure')"
    assert not result.native.stderr
