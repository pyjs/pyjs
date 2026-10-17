import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("dispatch", ["method", "captured", "property"])
@pytest.mark.parametrize("optional", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_callable_result_uses_declared_descriptor_abi(tmp_path, dispatch, optional, optimize):
    decorator = "@property" if dispatch == "property" else ""
    get = {"method": "callback = receiver.callback()",
           "captured": "method = receiver.callback; callback = method()",
           "property": "callback = receiver.callback"}[dispatch]
    returned = "Callable[[], int | None]" + (" | None" if optional else "")
    default = "None" if optional else "lambda: None"
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def answer() -> int:
            gc_collect()
            return 42
        class Base:
            {decorator}
            def callback(self) -> {returned}:
                return {default}
        class Child(Base):
            {decorator}
            def callback(self) -> Callable[[], int]:
                gc_collect()
                return answer
        def read(receiver: Base) -> str:
            {get}
            gc_collect()
            if callback is None:
                return "missing"
            return str(callback())
        def main() -> str:
            gc_set_threshold(1)
            return read(Base()) + ':' + read(Child()) + ':' + read(Base())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == ("missing:42:missing" if optional else "None:42:None")
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_callable_result_adapts_argument_and_return_views(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        def capture(value: object) -> int:
            gc_collect()
            return 42 if value == "input" else 0
        def empty(value: str) -> object:
            return None
        class Base:
            def callback(self) -> Callable[[str], object]:
                return empty
        class Child(Base):
            def callback(self) -> Callable[[object], int]:
                return capture
        def read(receiver: Base) -> str:
            callback = receiver.callback()
            gc_collect()
            return str(callback("input"))
        def main() -> str:
            gc_set_threshold(1)
            return read(Base()) + ':' + read(Child())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "None:42"
    assert result.native.stderr == ""


def test_callable_result_does_not_implicitly_change_numeric_domains():
    with pytest.raises(LLVMUnsupported, match="explicit numeric conversion"):
        transpile_llvm('''
            from collections.abc import Callable
            def answer() -> int: return 42
            def empty() -> float: return 0.0
            class Base:
                def callback(self) -> Callable[[], float]: return empty
            class Child(Base):
                def callback(self) -> Callable[[], int]: return answer
            def read(receiver: Base) -> str: return str(receiver.callback()())
            def main() -> str: return read(Child())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_callable_result_allocation_failure_unwinds_before_retry(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Callable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        def answer() -> int: return 42
        class Base:
            def callback(self) -> Callable[[], int | None]:
                return lambda: None
        class Child(Base):
            def callback(self) -> Callable[[], int]:
                return answer
        def main() -> int:
            receiver: Base = Child()
            saved: Callable[[], int | None] = receiver.callback()
            for failure in [1, 0, 1, 0]:
                callback = saved
                caught = False
                arm(failure)
                try:
                    callback = receiver.callback()
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if caught != (failure == 1):
                    return 1
                if caught and callback is not saved:
                    return 2
                if callback() != 42 or saved() != 42:
                    return 3
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
