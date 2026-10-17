"""Runtime static-method extraction uses the existing fixed callable ABI."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_callbacks_select_runtime_override_and_keep_direct_lookup(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def label(value: str) -> str:
        return 'base' + value
class Child(Base):
    @staticmethod
    def label(value: str) -> str:
        return 'child' + value
class Inherited(Child):
    pass
class Grand(Inherited):
    @staticmethod
    def label(value: str) -> str:
        return 'grand' + value
    def parent(self) -> Callable[[str], str]:
        alias = super()
        return alias.label
def bind(value: Base, events: list[str]) -> Callable[[str], str]:
    events.append('bind')
    return value.label
def receiver(events: list[str]) -> Base:
    events.append('receiver')
    return Grand()
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    callbacks = [bind(Base(), events), bind(Child(), events),
                 bind(Inherited(), events), bind(Grand(), events),
                 receiver(events).label, Grand().parent(), Base.label]
    gc_collect()
    result = [callback('!') for callback in callbacks]
    return '|'.join(result + events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_callback_can_select_bound_override_and_retain_temporary(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def value(number: int) -> int:
        return number + 1
class Counter(Base):
    def __init__(self, value: int):
        self.stored = [value]
    def value(self, number: int) -> int:
        self.stored[0] += number
        return self.stored[0]
class Child(Counter):
    pass
class StaticAgain(Child):
    @staticmethod
    def value(number: int) -> int:
        return number + 100
def bind(value: Base) -> Callable[[int], int]:
    return value.value
def make(number: int) -> Callable[[int], int]:
    return bind(Child(number))
def main() -> str:
    gc_set_threshold(1)
    callbacks: list[Callable[[int], int]] = [bind(Base()), make(10), bind(StaticAgain(0))]
    gc_collect()
    first = [callback(2) for callback in callbacks]
    gc_collect()
    second = [callback(3) for callback in callbacks]
    return str(first) + ':' + str(second)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_selected_static_callback_exceptions_and_void_results(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
class Base:
    @staticmethod
    def run(events: list[str], fail: bool) -> None:
        events.append('base')
class Child(Base):
    @staticmethod
    def run(events: list[str], fail: bool) -> None:
        events.append('child')
        if fail:
            raise ValueError('selected')
def bind(value: Base) -> Callable[[list[str], bool], None]:
    return value.run
def main() -> str:
    callback = bind(Child())
    events: list[str] = []
    try:
        callback(events, True)
    except ValueError:
        events.append('caught')
    callback(events, False)
    return ','.join(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("parameter, returned, body", [
    ("int", "bool", "True"),
    ("bool", "int", "1"),
    ("int", "int | None", "None"),
    ("int", "object", "number"),
])
def test_static_callback_overrides_require_the_fixed_callable_abi(parameter, returned, body):
    diagnostic = ("results require an explicit numeric conversion" if returned == "bool"
                  else "adapters require compatible arities and types")
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm(f'''
from collections.abc import Callable
class Base:
    @staticmethod
    def value(number: int) -> int:
        return number
class Child(Base):
    @staticmethod
    def value(number: {parameter}) -> {returned}:
        return {body}
def bind(value: Base) -> Callable[[int], int]:
    return value.value
def main() -> int:
    return bind(Child())(1)
''')


def test_union_static_method_value_diagnoses_instead_of_selecting_first_member():
    with pytest.raises(LLVMUnsupported, match="one shared runtime implementation"):
        transpile_llvm('''
from collections.abc import Callable
class A:
    @staticmethod
    def value() -> str:
        return 'a'
class B:
    @staticmethod
    def value() -> str:
        return 'b'
def bind(value: A | B) -> Callable[[], str]:
    return value.value
def main() -> str:
    return bind(A())() + bind(B())()
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_static_callback_with_one_inherited_implementation(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
class M:
    @staticmethod
    def value() -> str:
        return 'm'
class A(M):
    pass
class D(M):
    pass
def bind(value: A | D, events: list[str]) -> Callable[[], str]:
    events.append('bind')
    return value.value
def main() -> str:
    events: list[str] = []
    first = bind(A(), events)
    second = bind(D(), events)
    return first() + second() + ','.join(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("bound_override", [False, True])
def test_union_shared_static_declaration_checks_reached_subclass_overrides(bound_override):
    decorator = "" if bound_override else "@staticmethod"
    receiver = "self" if bound_override else ""
    with pytest.raises(LLVMUnsupported, match="one shared runtime implementation"):
        transpile_llvm(f'''
from collections.abc import Callable
class M:
    @staticmethod
    def value() -> str:
        return 'm'
class A(M):
    pass
class D(M):
    pass
class Override(A):
    {decorator}
    def value({receiver}) -> str:
        return 'override'
def bind(value: A | D) -> Callable[[], str]:
    return value.value
def main() -> str:
    return bind(Override())() + bind(D())()
''')


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("builtin, method, returned, application, value", [
    ("str", "__str__", "str", "'application'", "'text'"),
    ("list[int]", "copy", "list[int]", "[42]", "[7]"),
    ("object", "__str__", "str", "'application'", "object()"),
])
def test_static_union_callback_requires_proof_for_builtin_arms(
        reverse, builtin, method, returned, application, value):
    union = f"{builtin} | A" if reverse else f"A | {builtin}"
    with pytest.raises(LLVMUnsupported, match="one shared runtime implementation"):
        transpile_llvm(f'''
from collections.abc import Callable
class A:
    @staticmethod
    def {method}() -> {returned}:
        return {application}
def bind(value: {union}) -> Callable[[], {returned}]:
    return value.{method}
def main() -> str:
    return str(bind(A())()) + '|' + str(bind({value})())
''')


def test_static_union_callback_keeps_generic_specializations_distinct():
    # Equal source text/signatures do not prove specialized bodies interchangeable.
    with pytest.raises(LLVMUnsupported, match="one shared runtime implementation"):
        transpile_llvm('''
from collections.abc import Callable
class M[T]:
    @staticmethod
    def value() -> str:
        return 'm'
class A(M[int]):
    pass
class D(M[str]):
    pass
def bind(value: A | D) -> Callable[[], str]:
    return value.value
def main() -> str:
    return bind(A())() + bind(D())()
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_static_callbacks_preserve_portable_numeric_signatures(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs import int8, float32
class Base[T]:
    @staticmethod
    def value(number: int8) -> float32:
        return float32(number)
class Child[T](Base[T]):
    @staticmethod
    def value(number: int8) -> float32:
        return float32(number + int8(1))
def bind(value: Base[int]) -> Callable[[int8], float32]:
    return value.value
def main() -> str:
    base = bind(Base[int]())
    child = bind(Child[int]())
    return str(base(int8(127))) + ':' + str(child(int8(127)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_to_bound_callback_allocation_failure_recovers(tmp_path, optimize):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
from collections.abc import Callable
from tests.native.allocation_support import arm
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def value(number: int) -> int:
        return number
class Child(Base):
    def __init__(self, value: int):
        self.stored = value
    def value(self, number: int) -> int:
        return self.stored + number
def bind(value: Base) -> Callable[[int], int]:
    return value.value
def main() -> int:
    gc_set_threshold(1)
    child = Child(40)
    arm(1)
    caught = False
    try:
        failed = bind(child)
    except MemoryError:
        caught = True
    arm(0)
    assert caught
    callback = bind(child)
    gc_collect()
    assert callback(2) == 42
    return 0
''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
