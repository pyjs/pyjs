import pytest

from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import BYTES_CONSTRUCTION_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_typed_bytes_construction_contract(optimize):
    result = LLVM().assert_matches_python(BYTES_CONSTRUCTION_CONTRACT.source,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_protocol_precedence_subclasses_defaults_and_failure(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Source:
            def __init__(self, count: int, events: list[int]):
                self.count = count
                self.events = events
            def __iter__(self) -> Iterator[int]:
                self.events.append(1)
                return iter([65, 66])
        class Indexed(Source):
            def __index__(self) -> int:
                gc_collect()
                self.events.append(2)
                if self.count == 99:
                    raise RuntimeError("bad count")
                return self.count
        class Binary(Indexed):
            def __bytes__(self, value: int = 67) -> bytes:
                gc_collect()
                self.events.append(3)
                return bytes([value, value + 1])
        class CountOnly:
            def __index__(self) -> int8:
                return int8(2)
        class Broken(Binary):
            def __bytes__(self, value: int = 67) -> bytes:
                gc_collect()
                self.events.append(4)
                raise ValueError("bad bytes")
        def consume(value: Source) -> bytes:
            return bytes(value)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            results = [consume(Source(2, events)).hex(),
                       consume(Indexed(2, events)).hex(),
                       consume(Binary(99, events)).hex(), bytes(CountOnly()).hex()]
            try:
                consume(Indexed(99, events))
            except RuntimeError as error:
                results.append(str(error))
            try:
                consume(Indexed(-1, events))
            except ValueError as error:
                results.append(str(error))
            try:
                consume(Broken(99, events))
            except ValueError as error:
                results.append(str(error))
            return repr((results, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("source", ["[1.5]", "[None]", "[b'x']"])
def test_bytes_noninteger_item_storage_has_a_focused_boundary(source):
    with pytest.raises(LLVMUnsupported, match=r"LLVM bytes\(\) iterable items must be integers at line 2"):
        transpile_llvm(f"def main() -> bytes:\n    return bytes({source})\n")


def test_bytes_invalid_protocol_return_has_a_focused_boundary():
    with pytest.raises(LLVMUnsupported, match="LLVM __bytes__ requires an instance method returning bytes"):
        transpile_llvm('''
            class Invalid:
                def __bytes__(self) -> str:
                    return "wrong type"
            def main() -> bytes:
                return bytes(Invalid())
        ''')


def test_bytes_union_sources_require_narrowing_before_native_construction():
    with pytest.raises(LLVMUnsupported, match="LLVM bytes.*narrow unions before use"):
        transpile_llvm('''
            def build(value: bytes | int) -> bytes:
                return bytes(value)
            def main() -> bytes:
                return build(2)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_validates_each_item_before_fetching_again(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        def values(bad: int, events: list[int]) -> Iterator[int]:
            events.append(1)
            yield 65
            events.append(2)
            yield bad
            events.append(3)
            yield 66
            raise RuntimeError("after invalid byte")
        def collected() -> Iterator[int]:
            for value in range(300):
                gc_collect()
                yield value % 256
        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            for bad in [-1, 256]:
                events: list[int] = []
                iterator = values(bad, events)
                try:
                    bytes(iterator)
                except ValueError as error:
                    results.append(str(error))
                results.append(repr(events))
                results.append(str(next(iterator)))
                try:
                    next(iterator)
                except RuntimeError as error:
                    results.append(str(error))
                results.append(repr(events))
            results.append(bytes(collected()).hex())
            return "|".join(results)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_consumes_application_and_tuple_views_with_collecting_callbacks(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Source:
            def __init__(self, values: list[int], events: list[int]):
                self.values = values
                self.events = events
            def __iter__(self) -> Iterator[int]:
                self.events.append(1)
                gc_collect()
                return iter(self.values)
        class Derived(Source):
            def __iter__(self) -> Iterator[int]:
                self.events.append(2)
                gc_collect()
                return iter(self.values)
        def consume(value: Source) -> bytes:
            return bytes(value)
        def twice(value: Source) -> str:
            first = bytes(value)
            gc_collect()
            return first.hex() + ":" + bytes(value).hex()
        def tuple_view(value: tuple[int, ...]) -> bytes:
            return bytes(value)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = consume(Derived([0, 128, 255], events))
            second = twice(Source([1, 2, 3], events))
            third = tuple_view(tuple([4, 5, 6]))
            return repr((first, second, third, bytes(frozenset([7])), events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("protocol", ["__bytes__", "__index__"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_iterable_views_preserve_source_protocols(protocol, optimize):
    result_type, result = ("bytes", "b'custom'") if protocol == "__bytes__" else ("int", "3")
    comparison = LLVM().assert_matches_python(f'''
            from collections.abc import Iterable, Iterator
            class Source:
                def __iter__(self) -> Iterator[int]:
                    return iter([65, 66])
                def {protocol}(self) -> {result_type}:
                    return {result}
            def consume(value: Iterable[int]) -> bytes:
                return bytes(value)
            def main() -> str:
                return consume(Source()).hex()
        ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("protocol,result_type,result", [
    ("__bytes__", "bytes", "b'not callable'"),
    ("__index__", "int", "3"),
])
def test_bytes_property_protocol_is_not_called_as_a_method(protocol, result_type, result):
    with pytest.raises(LLVMUnsupported, match=f"LLVM {protocol} requires an instance method returning {result_type}"):
        transpile_llvm(f'''
            class Invalid:
                @property
                def {protocol}(self) -> {result_type}:
                    return {result}
            def main() -> str:
                return bytes(Invalid()).hex()
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("boolean", [False, True], ids=["int", "bool"])
def test_bytes_retains_custom_cursor_advancement_without_direct_next(optimize, boolean):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self):
                self.position = 0
            def __iter__(self) -> "Cursor":
                gc_collect()
                return self
            def __next__(self) -> {"bool" if boolean else "int"}:
                gc_collect()
                self.position += 1
                if self.position == 4:
                    raise StopIteration()
                return {"self.position == 2" if boolean else "self.position"}
        class Source:
            def __iter__(self) -> Cursor:
                gc_collect()
                return Cursor()
        def main() -> str:
            gc_set_threshold(1)
            return bytes(Cursor()).hex() + ":" + bytes(Source()).hex()
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_generator_acquisition_does_not_analyze_unrelated_cursor_methods(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        class Packet:
            def __iter__(self) -> Iterator[int]:
                yield 1
                yield 2
        class Reader:
            def __init__(self):
                self.done = False
            def __iter__(self) -> "Reader":
                return self
            def __next__(self) -> int:
                return unreachable_cursor_body
        def main() -> str:
            reader = Reader()
            return bytes(Packet()).hex() + str(reader.done)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("consume", ["bytes(Source()).hex()", "str([item for item in Source()])"])
def test_property_iteration_is_not_invoked_as_a_method(consume):
    with pytest.raises(LLVMUnsupported, match="LLVM application __iter__ requires an instance method"):
        transpile_llvm(f'''
            from collections.abc import Iterator
            class Source:
                @property
                def __iter__(self) -> Iterator[int]:
                    return iter([1])
            def main() -> str:
                return {consume}
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_protocol_free_base_uses_subclass_protocols_or_runtime_typeerror(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from enum import IntEnum
        class Base: pass
        class Binary(Base):
            def __bytes__(self) -> bytes:
                return b"binary"
        class Count(Base):
            def __index__(self) -> int:
                return 3
        class Items(Base):
            def __iter__(self) -> Iterator[int]:
                return iter([1, 2])
        class Size(IntEnum):
            TWO = 2
        def consume(value: Base) -> str:
            try:
                return bytes(value).hex()
            except TypeError as error:
                return str(error)
        def main() -> str:
            return repr((consume(Binary()), consume(Count()), consume(Items()),
                         consume(Base()), bytes(Size.TWO).hex()))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("value", ["1.5", "None"])
def test_bytes_unsupported_scalars_have_constructor_specific_diagnostics(value):
    with pytest.raises(LLVMUnsupported, match="LLVM bytes.*requires bytes, an integer count, or a typed integer iterable"):
        transpile_llvm(f"def main() -> str:\n    return bytes({value}).hex()\n")


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_bytes_construction_allocation_failures_are_recoverable(tmp_path, optimize, managed):
    # Measure and fail every allocation, not the old implementation's count:
    # reviewed native strings use separate header and payload allocations.
    build = '''
        def build(size: int, mode: int) -> bytes:
            if mode == 0:
                return bytes(size)
            if mode == 1:
                return bytes(range(size))
            if mode == 2:
                return bytes([value % 256 for value in range(size)])
            return bytes(value % 256 for value in range(size))
    ''' if managed else '''
        def build(size: int, mode: int) -> bytes:
            if mode == 0:
                return bytes(size)
            return bytes(range(size))
    '''
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining
        {build.strip()}
        def main() -> int:
            sentinel = b"unchanged"
            for size in range(0, 129, 64):
                for mode in range({4 if managed else 2}):
                    expected = build(size, mode)
                    arm(1000)
                    result = build(size, mode)
                    stages = 1000 - remaining()
                    arm(0)
                    if stages < 1 or result != expected:
                        return 1
                    for failure in range(1, stages + 1):
                        result = sentinel
                        caught = False
                        arm(failure)
                        try:
                            result = build(size, mode)
                        except MemoryError:
                            caught = True
                        arm(0)
                        {'gc_collect()' if managed else 'pass'}
                        if not caught or result is not sentinel:
                            return 2
                        if build(size, mode) != expected:
                            return 3
            try:
                bytes(9223372036854775807)
                return 4
            except MemoryError:
                pass
            arm(1)
            caught = False
            try:
                bytes(-1)
            except ValueError:
                caught = True
            untouched = remaining() == 1
            arm(0)
            if not caught or not untouched:
                return 5
            arm(1)
            empty = bytes()
            reused = bytes(sentinel)
            untouched = remaining() == 1
            arm(0)
            if not untouched or reused is not sentinel or empty != b"":
                return 6
            return 0
    ''')
    assert ("define ptr @pyjs.gc.try.alloc.described(" in source) is managed
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert not result.stdout and not result.stderr
