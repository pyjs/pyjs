"""Direct application-object calls share ordinary method binding and dispatch."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_objects_dispatch_overrides_and_constructed_receivers(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Add:
            def __init__(self, amount: int):
                self.amount = amount
            def __call__(self, value: int) -> int:
                return value + self.amount
        class Multiply(Add):
            def __call__(self, value: int) -> int:
                gc_collect()
                return value * self.amount
        def invoke(function: Add, value: int) -> int:
            return function(value)
        def main() -> int:
            gc_set_threshold(1)
            return invoke(Multiply(6), 7) + Add(3)(4)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_receiver_is_evaluated_once_and_rooted_before_later_arguments(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Callback:
            def __init__(self, text: str, events: list[str]):
                self.text, self.events = text, events
            def __call__(self, value: int, *, suffix: str = "!") -> str:
                self.events.append("call")
                gc_collect()
                return self.text + str(value) + suffix
        def receiver(events: list[str]) -> Callback:
            events.append("receiver")
            return Callback("value:", events)
        def argument(events: list[str]) -> int:
            events.append("argument")
            gc_collect()
            return 7
        def suffix(events: list[str]) -> str:
            events.append("suffix")
            gc_collect()
            return "?"
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            result = receiver(events)(argument(events), suffix=suffix(events))
            return result + ":" + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_callable_defaults_and_expanded_arguments_use_the_selected_method(optimize):
    result = LLVM().assert_matches_python('''
        import operator
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __call__(self, value: int = 2, *, scale: int = 3) -> int:
                gc_collect()
                return value * scale
        class Child(Base):
            def __call__(self, value: int = 7, *, scale: int = 11) -> int:
                gc_collect()
                return value * scale
        def invoke(callback: Base) -> str:
            values = [3]
            options = {"scale": 4}
            results = [callback(), callback(5), callback(scale=2),
                       callback(*values, **options), operator.call(callback, 6)]
            try:
                callback(*[1, 2])
            except TypeError:
                results.append(callback())
            return repr(results)
        def main() -> str:
            gc_set_threshold(1)
            return invoke(Base()) + ":" + invoke(Child())
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_mutable_defaults_remain_persistent_and_override_specific(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __call__(self, values: list[int] = []) -> str:
                gc_collect()
                values.append(1)
                return repr(values)
        class Child(Base):
            def __call__(self, values: list[int] = [9]) -> str:
                gc_collect()
                values.append(2)
                return repr(values)
        def invoke(callback: Base) -> str: return callback()
        def main() -> str:
            gc_set_threshold(1)
            return "|".join([invoke(Base()), invoke(Child()), invoke(Base()), invoke(Child())])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_results_preserve_generic_numeric_and_overload_representations(optimize):
    result = LLVM().assert_matches_python('''
        from typing import overload
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Box[T]:
            def __init__(self, value: T): self.value = value
            def __call__(self) -> T:
                gc_collect()
                return self.value
        class Narrow:
            def __call__(self, value: int8) -> int8: return value + int8(1)
        class Reader:
            @overload
            def __call__(self, key: int) -> int: ...
            @overload
            def __call__(self, key: str) -> str: ...
            def __call__(self, key: int | str) -> int | str:
                gc_collect()
                if isinstance(key, int):
                    if key == 0: return "wrong result"
                    return key + 1
                return key + "!"
        def main() -> str:
            gc_set_threshold(1)
            reader = Reader()
            result = repr((Box(7)(), Box("text")(), Box([1, 2])(),
                           int(Narrow()(int8(127))), str(reader(4)), reader("x")))
            try:
                value = reader(0)
                # CPython permits the deliberately dishonest overload. Native
                # checks the selected result before exposing integer storage.
                return result + ":" + str(isinstance(value, str))
            except TypeError:
                return result + ":True"
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_argument_allocation_failures_are_retryable(tmp_path, optimize):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm
        class Counter:
            def __init__(self, offset: int): self.offset = offset
            def __call__(self, *values: int, **named: int) -> int:
                gc_collect()
                return self.offset + sum(values) + sum(named.values())
        def main() -> int:
            gc_set_threshold(1)
            failures = 0
            for cutoff in range(1, 24):
                result = -1
                caught = False
                arm(cutoff)
                try:
                    result = Counter(2)(*[3, 4], extra=5)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if caught:
                    failures += 1
                    if result != -1: return 1
                elif result != 14:
                    return 2
                if Counter(2)(*[3, 4], extra=5) != 14: return 3
            return 0 if failures else 4
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("override", [
    "__call__ = None",
    "@staticmethod\n    def __call__(value: int) -> int: return value * 3",
    "@classmethod\n    def __call__(cls, value: int) -> int: return value * 3",
])
def test_noninstance_callable_overrides_cannot_use_the_inherited_slot(override):
    with pytest.raises(LLVMUnsupported, match="throughout the reached hierarchy") as caught:
        transpile_llvm(f'''
class Base:
    def __call__(self, value: int) -> int: return value + 1
class Child(Base):
    {override}
def invoke(value: Base) -> int: return value(2)
def main() -> int: return invoke(Child())
''', filename="callable_boundary.py")
    line = 6 + override.count("\n")
    assert any(f"callable_boundary.py:{line}:" in note for note in caught.value.__notes__)


def test_property_callable_override_is_rejected_before_dispatch():
    # Differing method signatures now bind dynamically; a property is still
    # not a method slot and must fail at the actual callable-object boundary.
    with pytest.raises(LLVMUnsupported, match="callable objects require ordinary instance __call__ methods") as caught:
        transpile_llvm('''
class Base:
    def __call__(self, value: int) -> int: return value + 1
class Child(Base):
    @property
    def __call__(self) -> int: return 3
def invoke(value: Base) -> int: return value(2)
def main() -> int: return invoke(Child())
''', filename="callable_boundary.py")
    assert any("callable_boundary.py:7:" in note for note in caught.value.__notes__)


@pytest.mark.parametrize("declaration", [
    "@staticmethod\n    def __call__(value: int) -> int: return value",
    "@classmethod\n    def __call__(cls, value: int) -> int: return value",
])
def test_noninstance_callable_declarations_have_a_located_diagnostic(declaration):
    with pytest.raises(CompilationError, match="ordinary instance __call__ method") as caught:
        transpile_llvm(f'''
class Value:
    {declaration}
def main() -> int: return Value()(2)
''', filename="callable_boundary.py")
    assert caught.value.lineno == 5


@pytest.mark.parametrize("optimize", [0, 2])
def test_loaded_callable_survives_detachment_and_propagates_errors(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __init__(self, text: str): self.text = text
            def __call__(self, value: int) -> str:
                gc_collect()
                if value < 0: raise ValueError(self.text)
                return self.text + str(value)
        class Child(Base):
            def __call__(self, value: int) -> str:
                return super().__call__(value) + "!"
        def detach(values: list[Base]) -> int:
            values.clear()
            gc_collect()
            return 7
        def main() -> str:
            gc_set_threshold(1)
            values: list[Base] = [Child("child")]
            result = values[0](detach(values))
            callback: Base = Child("failure")
            try:
                callback(-1)
            except ValueError as error:
                result += ":" + str(error)
            return result + ":" + callback(2)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_void_and_boolean_results(optimize):
    result = LLVM().assert_matches_python('''
        class Recorder:
            def __init__(self, values: list[int]): self.values = values
            def __call__(self, value: int) -> None: self.values.append(value)
        class Number:
            def __call__(self, value: int) -> bool: return value > 3
        def main() -> str:
            values: list[int] = []
            callback = Recorder(values)
            callback(3)
            callback(4)
            return repr(values) + ":" + str(Number()(2)) + ":" + str(Number()(5))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_callable_field_keeps_its_own_signature_and_inheritance(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def replacement(value: str) -> str:
            gc_collect()
            return "field:" + value
        class Base:
            def __init__(self): self.__call__: Callable[[str], str] = replacement
            def __call__(self, value: int) -> str: return "method:" + str(value)
        class Child(Base): pass
        def main() -> str:
            gc_set_threshold(1)
            return Base().__call__("base") + ":" + Child().__call__("child")
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
