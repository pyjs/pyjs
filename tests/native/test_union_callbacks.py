"""Union method extraction decodes and retains the selected receiver."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


def test_different_union_callback_result_layouts_are_not_reinterpreted():
    from tests.backend_semantics import UNION_CALLBACK_RESULT_CONTRACT
    with pytest.raises(LLVMUnsupported, match="compatible arities and types at line"):
        transpile_llvm(UNION_CALLBACK_RESULT_CONTRACT.source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_virtual_callback_is_rooted_before_later_argument_or_item(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self, text: str):
        self.text = text
    def value(self, suffix: str) -> str:
        return self.text + suffix
class A(Base):
    pass
class B(Base):
    def value(self, suffix: str) -> str:
        return 'B' + self.text + suffix
class Child(A):
    def value(self, suffix: str) -> str:
        return 'C' + self.text + suffix
def pick(flag: bool, events: list[str]) -> A | B:
    events.append('pick')
    if flag:
        return A('hello')
    return Child('child')
def later(events: list[str]) -> str:
    events.append('later')
    gc_collect()
    return '!'
def other(events: list[str]) -> Callable[[str], str]:
    events.append('other')
    gc_collect()
    return B('bye').value
def use(callback: Callable[[str], str], suffix: str) -> str:
    return callback(suffix)
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    first = use(pick(True, events).value, later(events))
    second = use(pick(False, events).value, later(events))
    callbacks = [pick(True, events).value, other(events)]
    return '|'.join([first, second, callbacks[0]('?'), callbacks[1]('.')] + events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("subclasses", [2, 30])
def test_union_callback_allocation_is_grouped_by_implementation(subclasses):
    declarations = ''.join(f'class S{i}(A):\n    pass\n' for i in range(subclasses))
    uses = ' + '.join(f'bind(S{i}())()' for i in range(subclasses))
    result = transpile_llvm(f'''
from collections.abc import Callable
class A:
    def value(self) -> str:
        return 'a'
class B:
    def value(self) -> str:
        return 'b'
{declarations}
def bind(value: A | B) -> Callable[[], str]:
    return value.value
def main() -> str:
    return bind(B())() + {uses}
''')
    # Whole-module IR includes unrelated runtime allocations. Only this binding
    # site should have one checked, precisely traced descriptor allocation per
    # implementation, not per class (the two pointer slots retain the receiver).
    body = result.split('define ptr @fn.bind(', 1)[1].split('\n}\n', 1)[0]
    assert body.count('call ptr @pyjs.gc.alloc.described(') == 2


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_callback_groups_keep_generic_specializations_distinct(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs.native import gc_collect, gc_set_threshold
class Box[T]:
    def __init__(self, item: T):
        self.item = item
    def label(self) -> str:
        return 'box:' + str(self.item)
class IntBox(Box[int]):
    pass
def bind(value: Box[int] | Box[str]) -> Callable[[], str]:
    return value.label
def main() -> str:
    gc_set_threshold(1)
    callbacks = [bind(Box(42)), bind(Box('text')), bind(IntBox(7))]
    gc_collect()
    return '|'.join(callback() for callback in callbacks)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_bound_callbacks_keep_receiver_and_runtime_override(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self, text: str):
        self.text = text
    def value(self, suffix: str) -> str:
        return self.text + suffix
class A(Base):
    pass
class B(Base):
    pass
class Child(A):
    def value(self, suffix: str) -> str:
        self.text += '!'
        return self.text + suffix
def bind(value: A | B) -> Callable[[str], str]:
    return value.value
def pick(events: list[str]) -> A | B:
    events.append('receiver')
    return Child('c')
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    callbacks = [bind(A('a')), bind(B('b')), pick(events).value]
    gc_collect()
    first = [callback('?') for callback in callbacks]
    gc_collect()
    second = [callback('.') for callback in callbacks]
    return '|'.join(first + second + events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_bound_callback_selects_static_override(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
class A:
    def value(self, number: int) -> int:
        return number + 1
class B:
    def value(self, number: int) -> int:
        return number + 2
class Child(A):
    @staticmethod
    def value(number: int) -> int:
        return number + 3
def bind(value: A | B) -> Callable[[int], int]:
    return value.value
def main() -> str:
    callbacks = [bind(A()), bind(B()), bind(Child())]
    return str([callback(10) for callback in callbacks])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("parameter, returned, body, message", [
    ("int", "bool", "True", "must preserve the base method signature"),
    ("bool", "int", "1", "must preserve the base method signature"),
    ("int", "int | None", "None", "overrides require compatible parameter and result types at line 2"),
    ("int", "object", "number", "overrides require compatible parameter and result types at line 2"),
])
def test_union_callback_subclass_rejects_incompatible_parameter_or_result(parameter, returned, body, message):
    # Covariant result adaptation does not permit widening the base contract
    # or implicitly converting distinct scalar input/output ABIs.
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
from collections.abc import Callable
class A:
    def value(self, number: int) -> int:
        return number
class B:
    def value(self, number: int) -> int:
        return number + 1
class Child(A):
    def value(self, number: {parameter}) -> {returned}:
        return {body}
def bind(value: A | B) -> Callable[[int], int]:
    return value.value
def main() -> int:
    return bind(Child())(1)
''')


@pytest.mark.parametrize("reverse", [False, True])
def test_union_callback_rejects_unmodeled_receiver_arms(reverse):
    annotation = "str | A" if reverse else "A | str"
    with pytest.raises(LLVMUnsupported, match="application receivers on every member"):
        transpile_llvm(f'''
from collections.abc import Callable
class A:
    def upper(self) -> str:
        return 'application'
def bind(value: {annotation}) -> Callable[[], str]:
    return value.upper
def main() -> str:
    return bind(A())() + bind('text')()
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_callback_allocation_failure_recovers(tmp_path, optimize):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
from collections.abc import Callable
from tests.native.allocation_support import arm
from pyjs.native import gc_collect, gc_set_threshold
class A:
    def __init__(self, value: int):
        self.value = value
    def get(self) -> int:
        return self.value
class B:
    def get(self) -> int:
        return 99
def bind(value: A | B) -> Callable[[], int]:
    return value.get
def main() -> int:
    gc_set_threshold(1)
    value = A(42)
    arm(1)
    caught = False
    try:
        failed = bind(value)
    except MemoryError:
        caught = True
    arm(0)
    assert caught
    callback = bind(value)
    gc_collect()
    assert callback() == 42
    assert bind(B())() == 99
    return 0
''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_unrelated_union_callbacks_propagate_exceptions_and_void(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from collections.abc import Callable
class A:
    def run(self, events: list[str], fail: bool) -> None:
        events.append('a')
class B:
    def run(self, events: list[str], fail: bool) -> None:
        events.append('b')
        if fail:
            raise ValueError('selected')
def bind(value: A | B) -> Callable[[list[str], bool], None]:
    return value.run
def main() -> str:
    events: list[str] = []
    callbacks = [bind(A()), bind(B())]
    for callback in callbacks:
        try:
            callback(events, True)
        except ValueError:
            events.append('caught')
        callback(events, False)
    return ','.join(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
