import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.native.llvm import transpile_llvm, transpile_llvm_module
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly import transpile_webassembly
from tests.backend_semantics import APPLICATION_ROUNDING_CONTRACT
from tests.native.allocation_support import run_allocation_case


def test_shared_application_rounding_contract():
    result = LLVM().assert_matches_python(APPLICATION_ROUNDING_CONTRACT.source)
    assert result.native.returncode == 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_erased_digits_omit_none_without_erasing_other_values(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class R:
            def __round__(self, digits: object = 7) -> str:
                gc_collect()
                return repr(digits)
        def rounded(digits: object) -> str:
            return round(R(), digits)
        def main() -> str:
            gc_set_threshold(1)
            return '/'.join(rounded(digits) for digits in [None, 2, 'x', False])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_intenum_keeps_scalar_results(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        class Code(IntEnum):
            VALUE = 125
            NEGATIVE = -125
        def rounded(value: Code) -> int:
            return round(value, -1)
        def main() -> str:
            return repr((round(Code.VALUE), round(Code.VALUE, None),
                         round(Code.VALUE, -1), rounded(Code.NEGATIVE)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_ignores_instance_fields_but_explicit_calls_keep_them(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def fake() -> int: return 42
        class R:
            def __init__(self):
                self.__round__: Callable[[], int] = fake
            def __round__(self) -> int:
                gc_collect()
                return 7
        class S(R):
            def __round__(self) -> int: return 8
        class Static:
            def __init__(self):
                self.__round__: Callable[[], int] = fake
            @staticmethod
            def __round__() -> int: return 9
        def nominal(value: R) -> int: return round(value)
        def union(value: R | Static) -> int: return round(value)
        def main() -> str:
            gc_set_threshold(1)
            value = R()
            return repr((round(value), value.__round__(), nominal(S()),
                         union(value), union(Static())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_round_instance_field_cannot_supply_the_class_protocol():
    with pytest.raises(CompilationError, match="instance or static __round__") as caught:
        transpile_llvm('''
            from collections.abc import Callable
            def fake() -> int: return 42
            class R:
                def __init__(self): self.__round__: Callable[[], int] = fake
            def main() -> int: return round(R())
        ''')
    assert caught.value.lineno == 6


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_runtime_subclasses_can_disable_and_restore_the_protocol(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __round__(self, digits: int = 7) -> int:
                gc_collect()
                return digits
        class Disabled(Base):
            __round__ = None
        class Restored(Disabled):
            def __round__(self, digits: int = 9) -> int:
                return digits + 1
        class Other:
            @staticmethod
            def __round__(digits: int = 3) -> int: return digits
        def nominal(value: Base) -> str:
            try:
                return str(round(value))
            except TypeError:
                return 'disabled'
        def union(value: Base | Other, digits: int | None) -> str:
            try:
                return str(round(value, digits))
            except TypeError:
                return 'disabled'
        def main() -> str:
            gc_set_threshold(1)
            return repr((nominal(Base()), nominal(Disabled()), nominal(Restored()),
                         union(Disabled(), None), union(Restored(), None), union(Other(), 4)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("compile", [transpile_llvm, transpile_jvm, transpile_webassembly],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", ["round(1.5, 'x')", "round(1.5, 2.0)",
                                        "round(15, 2.0)", "round(2.5, [1])"])
def test_round_bad_scalar_digits_keep_shared_argument_diagnostics(compile, expression):
    with pytest.raises(CompilationError, match="Argument 'ndigits'.*expects int.*PYJS1104") as caught:
        compile(f"def main() -> object:\n    return {expression}\n", filename="bad_round.py")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("compile", [transpile_llvm, transpile_jvm, transpile_webassembly],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", ["round('x')", "round(None)", "round([1])"])
def test_round_bad_builtin_receivers_keep_shared_argument_diagnostics(compile, expression):
    with pytest.raises(CompilationError, match="Argument 'number'.*expects a number.*PYJS1104") as caught:
        compile(f"def main() -> object:\n    return {expression}\n", filename="bad_round.py")
    assert caught.value.lineno == 2


@pytest.mark.parametrize("compile", [transpile_llvm, transpile_jvm, transpile_webassembly],
                         ids=["llvm", "jvm", "wasm"])
def test_round_aliases_keep_shared_structured_diagnostics(compile):
    with pytest.raises(CompilationError, match="instance or static __round__ method.*PYJS2001") as caught:
        compile('''
class Value:
    def alternate(self) -> int: return 4
    __round__ = alternate
def main() -> int:
    return round(Value())
''', filename="round_alias.py")
    assert caught.value.lineno == 6


@pytest.mark.parametrize("compile", [transpile_jvm, transpile_webassembly], ids=["jvm", "wasm"])
def test_round_application_star_pack_keeps_shared_structured_diagnostic(compile):
    # LLVM rejects this pack earlier; JVM/WASM reach application_round's guard.
    with pytest.raises(CompilationError, match="native application round requires statically bound arguments.*PYJS2001") as caught:
        compile('''
class Value:
    def __round__(self, digits: int | None = None) -> int: return 4
def main() -> int:
    args = (Value(),)
    return round(*args)
''', filename="round_pack.py")
    assert caught.value.lineno == 6


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_application_protocols_dispatch_virtually_and_omit_none(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int):
                self.value = value
            def __round__(self, digits: int = 7) -> int:
                gc_collect()
                return self.value + digits
        class Shifted(Value):
            def __round__(self, digits: int = 7) -> int:
                return super().__round__(digits) + 2
        def rounded(value: Value, digits: int | None) -> int:
            return round(value, ndigits=digits)
        def main() -> str:
            gc_set_threshold(1)
            values: list[Value] = [Value(10), Shifted(20)]
            return repr([(round(value), round(value, None), rounded(value, None),
                          rounded(value, 3), round(number=value, ndigits=4))
                         for value in values])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_forwards_noninteger_digits_and_arbitrary_results(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect
        class Label:
            def __round__(self, suffix: str = 'default') -> str:
                gc_collect()
                return 'rounded:' + suffix
        class Box:
            def __init__(self, value: int):
                self.value = value
        class Factory:
            def __round__(self) -> Box:
                gc_collect()
                return Box(42)
        class Small:
            def __round__(self, digits: int8 = 7) -> int8:
                return digits + int8(1)
        def label(suffix: str | None) -> str:
            return round(Label(), suffix)
        def small(digits: int8 | None) -> int8:
            return round(Small(), digits)
        def main() -> str:
            return repr((label(None), label('yes'), round(Label(), ndigits='keyword'),
                         round(Factory()).value, round(Small()), round(Small(), int8(127)),
                         small(None), small(int8(127))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_keyword_order_callbacks_and_exception_recovery(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, events: list[str]):
                self.events = events
            def __round__(self, digits: int = 7) -> int:
                self.events.append('round')
                gc_collect()
                if digits == 9:
                    raise LookupError('callback')
                return digits
        def receiver(events: list[str]) -> Value:
            events.append('number')
            gc_collect()
            return Value(events)
        def digits(events: list[str], value: int | None) -> int | None:
            events.append('digits')
            gc_collect()
            return value
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            results: list[int] = []
            for value in [None, 3, 9, 4]:
                events.clear()
                try:
                    results.append(round(ndigits=digits(events, value), number=receiver(events)))
                except LookupError:
                    results.append(-1)
                assert events == ['digits', 'number', 'round']
            events.clear()
            results.append(round(receiver(events), digits(events, None)))
            assert events == ['number', 'digits', 'round']
            return repr(results)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_lexical_bindings_work_in_nested_calls_and_closures(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterator
        class Value:
            def __init__(self, value: int):
                self.value = value
            def __round__(self, digits: int = 1) -> int:
                return self.value + digits
        def values() -> Iterator[int]:
            for index in range(3):
                yield round(Value(index), round(Value(4)))
        def main() -> str:
            offset = 5
            callback: Callable[[int], int] = lambda value: round(Value(value + offset), None)
            rows = [callback(value) for value in values()]
            offset = 7
            return repr((rows, callback(2), sum(round(Value(x)) for x in range(3))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_round_scalar_ir_stays_free_of_application_dispatch():
    source = transpile_llvm('def main() -> int: return round(1.5) + round(25, -1)')
    assert '@pyjs.gc.' not in source
    assert 'call double @llvm.roundeven.f64' in source


@pytest.mark.parametrize("name", ["int", "bool", "float"])
def test_round_application_names_are_not_builtin_identity(name):
    result = LLVM().assert_matches_python(f'''
        from __future__ import annotations
        class {name}:
            def __round__(self, digits: {name} | None = None) -> str:
                return 'omitted' if digits is None else 'provided'
        def main() -> str:
            return round({name}()) + '/' + round({name}(), {name}())
    ''', sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_method_overloads_choose_and_join_result_types(optimize):
    result = LLVM().assert_matches_python('''
        from typing import overload
        class Value:
            @overload
            def __round__(self) -> int: ...
            @overload
            def __round__(self, digits: int) -> str: ...
            def __round__(self, digits: int | None = None) -> int | str:
                if digits is None:
                    return 42
                return 'digits:' + str(digits)
        def rounded(digits: int | None) -> int | str:
            return round(Value(), digits)
        def main() -> str:
            # An inferred integer overload view retains possible bool identity;
            # integer-only annotated storage intentionally requires int(...).
            value = round(Value())
            text: str = round(Value(), 3)
            return repr((value + 1, text.upper(), rounded(None), rounded(4)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_static_and_union_methods_use_normal_call_semantics(optimize):
    result = LLVM().assert_matches_python('''
        class Static:
            @staticmethod
            def __round__(digits: int = 7) -> int:
                return digits
        class Instance:
            def __round__(self, digits: int = 7) -> int:
                return digits + 1
        def receiver(events: list[str]) -> Static:
            events.append('receiver')
            return Static()
        def rounded(value: Static | Instance, digits: int | None) -> int:
            return round(value, digits)
        def main() -> str:
            events: list[str] = []
            answer = round(receiver(events), 3)
            assert events == ['receiver']
            return repr((answer, rounded(Static(), None), rounded(Instance(), 4)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("declaration", [
    "@property\n    def __round__(self) -> int: return 3",
    "@classmethod\n    def __round__(cls) -> int: return 3",
])
def test_round_unsupported_descriptors_have_a_located_diagnostic(declaration):
    with pytest.raises(CompilationError, match="instance or static __round__") as caught:
        transpile_llvm(f"class R:\n    {declaration}\ndef main() -> object:\n    return round(R())\n",
                       filename="round_descriptor.py")
    assert caught.value.lineno == 5


def test_round_application_packs_have_a_focused_boundary():
    with pytest.raises(CompilationError, match="concrete, non-overloaded signature") as caught:
        transpile_llvm('''
            class R:
                def __round__(self, digits: int = 7) -> int: return digits
            def main() -> int: return round(*[R()])
        ''')
    assert caught.value.lineno == 4


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_allocation_failure_unwinds_and_retry_preserves_results(tmp_path, optimize):
    module = transpile_llvm_module('''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm
        class R:
            def __init__(self, value: int): self.value = value
            def __round__(self, digits: int = 7) -> list[int]:
                gc_collect()
                return [self.value, digits]
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            original = R(42)
            for stage in range(1, 40):
                result = [-1]
                success = False
                try:
                    arm(stage)
                    result = round(original, None)
                    arm(0)
                    success = True
                except MemoryError:
                    arm(0)
                    caught += 1
                    assert result == [-1]
                finally:
                    arm(0)
                gc_collect()
                assert original.value == 42
                assert round(original) == [42, 7]
                if success:
                    assert result == [42, 7] and caught > 0
                    return 0
            return 1
    ''')
    result = run_allocation_case(module.llvm_ir, tmp_path, managed=module.managed, optimize=optimize)
    assert result.stdout == result.stderr == b""
