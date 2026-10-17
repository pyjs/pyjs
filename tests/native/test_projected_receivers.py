"""Projected instance results are not class-qualified method receivers."""

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "left(events) + (yield from child(events))",
    "(yield from child(events)).read(left(events))",
    "(yield from child(events)).label()",
])
def test_delegated_instance_result_remains_a_method_receiver(tmp_path, optimize, expression):
    result = LLVM().assert_matches_python(f'''
from collections.abc import Generator
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self, events: list[str]):
        self.events = events
        self.values = [9]
    def __radd__(self, value: int) -> int:
        gc_collect()
        self.events.append("add")
        return value + self.values[0]
    def read(self, value: int) -> int:
        gc_collect()
        self.events.append("read")
        return value + self.values[0]
    @staticmethod
    def label() -> int:
        return 10
class Child(Base):
    @staticmethod
    def label() -> int:
        gc_collect()
        return 20
def left(events: list[str]) -> int:
    events.append("left")
    return 7
def child(events: list[str]) -> Generator[int, None, Base]:
    events.append("child")
    yield 1
    gc_collect()
    return Child(events)
def source(events: list[str]) -> Generator[int, None, None]:
    try:
        yield {expression}
    finally:
        events.append("cleanup")
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    values = list(source(events))
    gc_collect()
    return str(values) + str(events) + str(Base.label())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
