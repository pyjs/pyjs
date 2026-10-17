import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_erased_pack_failure_preserves_assignment_and_recovers(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def text(value: object) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, int):
                return str(int(value))
            return "?"

        def combine(*values: object, **named: object) -> str:
            {"gc_collect()" if managed else "pass"}
            output = ""
            for value in values:
                output += text(value)
            for key, value in named.items():
                output += text(value)
            return output

        class Packed:
            def __init__(self, *values: object, **named: object):
                {"gc_collect()" if managed else "pass"}
                self.label = combine(*values, **named)

        def main() -> int:
            {"gc_set_threshold(1)" if managed else "pass"}
            failures = 0
            for mode in range(4):
                for cutoff in range(1, 18):
                    previous = "sentinel"
                    caught = False
                    arm(cutoff)
                    try:
                        if mode == 0:
                            previous = combine(3, "x", value=5)
                        elif mode == 1:
                            previous = combine(*[3], **{{"value": "x5"}})
                        elif mode == 2:
                            previous = Packed(3, "x", value=5).label
                        else:
                            previous = Packed(*[3], **{{"value": "x5"}}).label
                    except MemoryError:
                        caught = True
                    arm(0)
                    {"gc_collect()" if managed else "pass"}
                    if caught:
                        failures += 1
                        if previous != "sentinel":
                            return 1
                    elif previous != "3x5":
                        return 2
                    if combine(3, "x", value=5) != "3x5":
                        return 3
            return 0 if failures > 0 else 4
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("collect", [False, True])
def test_pack_failure_precedes_body_and_keeps_keyword_error_priority(tmp_path, optimize, collect):
    source = transpile_llvm(f'''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining

        class Counter:
            def __init__(self):
                self.entered = 0

        def positional(counter: Counter, /, first: int, *items: int) -> int:
            counter.entered += 1
            return first + len(items)

        def named(counter: Counter, /, first: int, *, extra: int = 4) -> int:
            counter.entered += 1
            return first + extra

        def merged(counter: Counter, /, **values: object) -> int:
            counter.entered += 1
            return len(values)

        def keywords(counter: Counter, /, **values: int) -> int:
            counter.entered += 1
            return len(values)

        class Record:
            def __init__(self, counter: Counter, /, **values: int):
                counter.entered += 1
                self.count = len(values)

        def main() -> int:
            {"gc_set_threshold(1)" if collect else "pass"}
            counter = Counter()
            for mode in range(8):
                stages = 1
                failure = 0
                while failure <= stages:
                    # Keep each sweep cold, independent of lazy mapping metadata.
                    numbers = list(range(12))
                    values = {{str(index): int(int8(index)) for index in range(12)}}
                    strings = {{"s" + str(index): str(index) for index in range(12)}}
                    small = {{"first": 3, "extra": 5}}
                    duplicate = {{"first": 9}}
                    counter.entered = 0
                    result = -1
                    memory_error = False
                    type_error = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        if mode == 0:
                            result = positional(counter, *numbers)
                        elif mode == 1:
                            result = named(counter, **small)
                        elif mode == 2:
                            result = merged(counter, **values, **strings)
                        elif mode == 3:
                            result = Record(counter, **values).count
                        elif mode == 4:
                            result = keywords(counter, first=0, **values, last=13)
                        elif mode == 5:
                            result = keywords(counter, first=0, **values, **duplicate)
                        elif mode == 6:
                            result = keywords(counter, **values, **duplicate, first=0)
                        else:
                            result = positional(counter, 1, *numbers, 9)
                    except MemoryError:
                        memory_error = True
                    except TypeError:
                        type_error = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {"gc_collect()" if collect else "pass"}
                    assert stages > 0 and memory_error == (failure != 0)
                    assert type_error == (failure == 0 and mode in (5, 6))
                    if memory_error or type_error:
                        assert counter.entered == 0 and result == -1
                    else:
                        assert counter.entered == 1
                        assert result == (11 if mode == 0 else 8 if mode == 1 else
                                          24 if mode == 2 else 12 if mode == 3 else 14)
                    assert numbers == list(range(12))
                    assert len(values) == 12 and values["11"] == 11
                    assert len(strings) == 12 and strings["s11"] == "11"
                    assert small == {{"first": 3, "extra": 5}} and duplicate == {{"first": 9}}
                    assert positional(counter, *numbers) == 11
                    assert named(counter, **small) == 8
                    assert merged(counter, **values, **strings) == 24
                    assert Record(counter, **values).count == 12
                    failure += 1
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=collect, optimize=optimize)
    assert result.stdout == result.stderr == b""
