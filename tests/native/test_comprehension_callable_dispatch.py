import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_comprehension_calls_dispatch_on_callable_results(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self, value: int):
        self.value = value
    def name(self) -> str:
        return "Base" + str(self.value)
class Child(Base):
    def name(self) -> str:
        gc_collect()
        return "Child" + str(self.value)
def make(value: Base) -> Base:
    return Child(value.value)
class Factory:
    def get(self) -> Callable[[Base], Base]:
        return make
def main() -> str:
    gc_set_threshold(1)
    objects = [Factory()]
    value = Base(2)
    eager = [obj.get()(value).name() for obj in objects]
    lazy = list(obj.get()(value).name() for obj in objects)
    constructed = [Base(3).name() for obj in objects]
    return repr((eager, lazy, constructed))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
