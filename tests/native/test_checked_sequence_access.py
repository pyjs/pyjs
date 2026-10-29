import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_checked_sequence_access_keeps_bounds_mutations_and_payloads(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        def index(values: list[int], events: list[int]) -> int:
            events.append(1)
            values.append(30)
            return -1

        def main() -> str:
            gc_set_threshold(1)
            result: list[str] = []
            values = [10, 20]
            events: list[int] = []
            result.append(str(values[index(values, events)]))
            result.append(repr(events))
            alias = values
            alias[-3] = 11
            result.append(str(values.pop(-2)))
            del values[-1]
            result.append(repr(alias))
            for i in [-9223372036854775808, -2, 1, 9223372036854775807]:
                try:
                    result.append(str(values[i]))
                except IndexError as error:
                    result.append(str(error))
                try:
                    values[i] = 99
                except IndexError as error:
                    result.append(str(error))
                try:
                    values.pop(i)
                except IndexError as error:
                    result.append(str(error))
                try:
                    del values[i]
                except IndexError as error:
                    result.append(str(error))
            empty: list[int] = []
            try:
                empty.pop()
            except IndexError as error:
                result.append(str(error))
            for i in [-1, 0]:
                try:
                    result.append(str(empty[i]))
                except IndexError as error:
                    result.append(str(error))
            small: list[int8] = [int8(3), int8(4)]
            small[-1] = int8(129)
            result.append(str(small.pop(-1)))
            floats: list[float32] = [float32(1.25), float32(2.5)]
            floats[-1] = float32(3.5)
            result.append(str(floats[-1]))
            flags = [True, False]
            flags[-1] = True
            result.append(str(flags[-1]))
            boxes = [Box(7), Box(8)]
            boxes[-2] = boxes[-1]
            gc_collect()
            result.append(str(boxes[-2] is boxes[-1]))
            nullable: list[str | None] = ["one", None]
            nullable[-2] = None
            nullable[-1] = "two"
            gc_collect()
            result.append(repr(nullable))
            nullable_numbers: list[int | None] = [None, 41, None]
            nullable_numbers[-1] = nullable_numbers[-2]
            nullable_numbers[-2] = None
            result.append(repr(nullable_numbers))
            pairs = [(1, 2), (3, 4)]
            pairs[-1] = pairs[-2]
            result.append(str(pairs[-1][1]))
            fixed = (7, 8)
            variable: tuple[int, ...] = (9, 10, 11)
            result.append(str(fixed[-1]) + str(variable[-2]))
            return "|".join(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_sequence_access_uses_one_checked_position():
    generated = transpile_llvm('''
        def read(values: list[int], index: int) -> int:
            return values[index]
        def main() -> int:
            return read([7, 8], -1)
    ''')
    # The module includes the runtime's public checked helper. Application
    # accesses must retain their exception guard, not call that helper again.
    body = generated.split("define i64 @fn.read(", 1)[1].split("\n}", 1)[0]
    assert body.count("icmp ult i64") == 1
    assert "@exception.type.pyjs.python.native.IndexError" in body
    assert "call ptr @pyjs.list.get" not in body
    assert "getelementptr i64, ptr" in body
