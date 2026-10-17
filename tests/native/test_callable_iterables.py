import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


def test_shared_callable_iterables(tmp_path):
    from tests.backend_semantics import CALLABLE_ITERABLE_CONTRACT
    comparison = LLVM().assert_matches_python(CALLABLE_ITERABLE_CONTRACT.source, directory=tmp_path,
                                             sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_unconverted_callable_signature_does_not_reach_iteration_body(tmp_path):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable, Iterator

        class Rows:
            def __iter__(self) -> Iterator[int]:
                return not_defined()

        def concrete(value: Rows) -> int:
            return 7

        def run(callback: Callable[[Rows], int]) -> int:
            return callback(Rows())

        def consume(values: Iterable[int]) -> int:
            return sum(values)

        def main() -> int:
            return run(concrete) + consume([1, 2])
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_identity_composes_with_application_iterator_handles(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self):
                self.index = 0
            def __iter__(self) -> Cursor:
                return self
            def __next__(self) -> int:
                if self.index == 2:
                    raise StopIteration()
                self.index += 1
                return self.index
        def adapt(value: Cursor) -> Iterator[int]:
            return value
        def expose(value: Iterator[int]) -> Iterable[int]:
            return value
        def optional(value: Iterator[int] | None) -> Iterable[int] | None:
            return value
        def same(view: Iterable[int], iterator: Iterator[int], original: Cursor) -> bool:
            gc_collect()
            return view is iterator and iterator is view and view is original and original is view
        def optional_same(view: Iterable[int] | None, original: Cursor | None) -> bool:
            gc_collect()
            return view is original and original is view
        def main() -> str:
            gc_set_threshold(1)
            original = Cursor()
            iterator = adapt(original)
            first = expose(iterator)
            second = expose(adapt(original))
            gc_collect()
            assert first is second
            assert same(first, iterator, original)
            assert optional_same(optional(iterator), original)
            assert optional_same(optional(None), None)
            assert first is not expose(adapt(Cursor()))
            return str(list(first)) + ':' + str(list(second))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("item_type", ["int", "object"])
def test_only_the_pinned_iterable_and_source_survive_collection(tmp_path, optimize, item_type):
    from pyjs.native.runtime import collector, heap
    from pyjs.native.runtime.pointers import Pointer
    from tests.native.runtime_support import runtime_functions

    library = LLVM().compile_library(f'''
        from collections.abc import Iterable
        from pyjs.native import gc_collect, gc_pin, gc_set_threshold
        def build() -> Iterable[{item_type}]:
            return [3, 4]
        def main(count: int) -> str:
            gc_set_threshold(1)
            view = build()
            for index in range(count):
                view = build()
                assert list(view) == [3, 4]
                gc_collect()
            gc_pin(view)
            return repr(list(view))
    ''', tmp_path, optimize=optimize)
    try:
        assert library.render(100) == "[3, 4]"
        invoke = runtime_functions({"pyjs.gc.try.collect": collector.try_collect}, library._library)
        assert invoke("pyjs.gc.try.collect", Pointer(library._heap))
        # The descriptor, list header and item buffer remain, not past views
        # or temporary cursors. This ctypes retention check is unsanitized;
        # executable parity/ownership tests above run ASan and UBSan.
        assert heap._Heap.from_address(library._heap).count == 3
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_builtin_sources_and_nested_storage(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        def consume(values: Iterable[int]) -> str:
            gc_collect()
            return repr((bool(values), list(values), list(values)))

        def main() -> str:
            gc_set_threshold(1)
            mapping = {2: 3, 4: 5}
            sources: list[Iterable[int]] = [range(2), b"ab", mapping.keys(), mapping.values(), ()]
            gc_collect()
            result = ""
            for values in sources:
                result += consume(values)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("expression", ["left == right", "left != right", "hash(left)", "repr(left)",
                                        "reversed(left)", "isinstance(left, list)"])
def test_unsupported_iterable_operations_are_diagnosed(expression):
    with pytest.raises((LLVMUnsupported, CompilationError)):
        transpile_llvm(f'''
            from collections.abc import Iterable
            def consume(left: Iterable[int], right: Iterable[int]) -> int:
                {expression}
                return 0
            def main() -> int:
                values = [3]
                return consume(values, values)
        ''')


@pytest.mark.parametrize("actual,target", [("list[bool]", "int"), ("list[int]", "float")])
def test_iterable_view_requires_explicit_numeric_item_conversion(actual, target):
    with pytest.raises(LLVMUnsupported, match="explicit numeric conversion"):
        transpile_llvm(f'''
            from collections.abc import Callable, Iterable
            def consume(values: Iterable[{target}]) -> int:
                return 0
            def factory() -> Callable[[{actual}], int]:
                return consume
            def main() -> int:
                factory()
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_iterable_views_and_captured_narrowing(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        def expose(value: list[int] | None) -> Iterable[int] | None:
            return value

        def consume(value: Iterable[int] | None) -> int:
            if value is None:
                return -1
            return sum(value)

        def reader(value: list[int]) -> Callable[[], int]:
            held: Iterable[int] = value
            return lambda: consume(held)

        def main() -> str:
            gc_set_threshold(1)
            result: list[int] = []
            inputs: list[list[int] | None] = [None, [2, 3], []]
            for value in inputs:
                view = expose(value)
                gc_collect()
                result.append(consume(view))
            assert expose(None) is None
            values = [4]
            callback = reader(values)
            values.append(5)
            gc_collect()
            return repr((result, callback()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_conversion_keeps_iterator_state_and_truth_failures_retryable(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Rows:
            def __init__(self):
                self.fail = True
            def __bool__(self) -> bool:
                gc_collect()
                if self.fail:
                    raise ValueError("truth")
                return False
            def __iter__(self) -> Iterator[int]:
                return iter([7])

        def expose(rows: Rows) -> Iterable[int]:
            return rows

        def cursor(values: Iterator[int]) -> Iterable[int]:
            return values

        def main() -> str:
            gc_set_threshold(1)
            rows = Rows()
            view = expose(rows)
            caught = False
            try:
                bool(view)
            except ValueError:
                caught = True
            assert caught
            rows.fail = False
            assert not view
            assert list(view) == [7]
            source = iter([2, 3])
            held = cursor(source)
            assert iter(held) is source
            first = list(held)
            second = list(held)
            return repr((bool(held), first, second))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_storage_identity_live_mutation_and_independent_cursors(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        class Holder:
            def __init__(self, values: Iterable[str]):
                self.values = values

        def identity(values: Iterable[str], original: dict[str, int]) -> bool:
            return values is original

        def expose(values: dict[str, int]) -> Iterable[str]:
            return values

        def main() -> str:
            gc_set_threshold(1)
            original = {"a": 1}
            assert identity(original, original)
            first = expose(original)
            second = expose(original)
            assert first is second
            holder = Holder(first)
            gc_collect()
            original["b"] = 2
            left = iter(holder.values)
            right = holder.values.__iter__()
            result = next(left) + next(left) + next(right)
            del original["a"]
            try:
                next(left)
            except RuntimeError:
                result += "changed"
            return result + str(list(holder.values))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_views_preserve_late_subclass_truth_and_cursor_protocols(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __len__(self) -> int:
                return 0
            def __iter__(self) -> Iterator[int]:
                return iter([1])

        class Child(Base):
            def __bool__(self) -> bool:
                gc_collect()
                return True
            def __iter__(self) -> Iterator[int]:
                gc_collect()
                return iter([7])

        def consume(values: Iterable[int]) -> int:
            return sum(values) if values else -1

        def factory() -> Callable[[Base], int]:
            return consume

        def source(value: Base) -> Iterable[int]:
            return value

        def main() -> int:
            gc_set_threshold(1)
            callback = factory()
            value: Base = Child()
            assert callback(value) == 7
            view = source(value)
            gc_collect()
            return consume(view)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_iterable_parameters_and_results_preserve_keys_and_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        def consume(values: Iterable[str]) -> str:
            gc_collect()
            return repr((bool(values), list(values), list(values)))

        def sequence() -> Callable[[list[str]], str]:
            return consume

        def mapping() -> Callable[[dict[str, int]], str]:
            return consume

        def pair() -> Callable[[tuple[str, str]], str]:
            return consume

        def empty() -> Callable[[tuple[()]], str]:
            return consume

        def text() -> Callable[[str], str]:
            return consume

        def members() -> Callable[[set[str]], str]:
            return consume

        def frozen() -> Callable[[frozenset[str]], str]:
            return consume

        def rows() -> dict[str, int]:
            return {"first": 1, "second": 2}

        def producer() -> Callable[[], Iterable[str]]:
            return rows

        def main() -> str:
            gc_set_threshold(1)
            callback = mapping()
            source = producer()
            gc_collect()
            assert callback is consume
            assert source is rows
            values = source()
            return "|".join((sequence()(["a", "b"]), callback(rows()),
                             pair()(("x", "y")), empty()(()), text()("é😀"),
                             members()({"set"}), frozen()(frozenset(["frozen"])),
                             consume(values), sequence()([])))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_iterable_protocols_remain_reachable_and_retry_after_failure(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Rows:
            def __init__(self, events: list[str]):
                self.events = events
                self.values = [3, 4]
                self.fail = False

            def __bool__(self) -> bool:
                self.events.append("truth")
                gc_collect()
                return bool(self.values)

            def __iter__(self) -> Iterator[int]:
                self.events.append("iterate")
                gc_collect()
                if self.fail:
                    raise ValueError("not ready")
                return iter(self.values)

        def consume(values: Iterable[int], events: list[str]) -> int:
            events.append("entered")
            gc_collect()
            total = 0
            if values:
                total = sum(values) + sum(values)
            return total

        def factory() -> Callable[[Rows, list[str]], int]:
            return consume

        class Reader:
            def __init__(self, events: list[str]):
                self.events = events

            def rows(self) -> Rows:
                return Rows(self.events)

        def producer(reader: Reader) -> Callable[[], Iterable[int]]:
            return reader.rows

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            callback = factory()
            rows = Rows(events)
            result = -1
            for fail in [True, False, True, False]:
                rows.fail = fail
                saved = result
                try:
                    result = callback(rows, events)
                except ValueError:
                    assert result == saved
                    events.append("caught")
                gc_collect()
            source = producer(Reader(events))
            gc_collect()
            result += consume(source(), events)
            return repr((result, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_callable_conversions_retain_indirect_iterable_methods(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Rows:
            def __init__(self):
                self.values = [5, 7]

            def __iter__(self) -> Iterator[int]:
                gc_collect()
                return iter(self.values)

        def total(values: Iterable[int]) -> int:
            return sum(values)

        def invoke(callback: Callable[[Rows], int], values: Rows) -> int:
            gc_collect()
            return callback(values)

        def factory() -> Callable[[Callable[[Iterable[int]], int], Rows], int]:
            return invoke

        def main() -> str:
            gc_set_threshold(1)
            return str(factory()(total, Rows()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_iterable_parameters_preserve_explicit_numeric_items(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def small(values: Iterable[int8]) -> int8:
            gc_collect()
            total = int8(0)
            for value in values:
                total += value
            return total

        def large(values: Iterable[int64]) -> int64:
            gc_collect()
            total = int64(0)
            for value in values:
                total += value
            return total

        def narrow() -> Callable[[list[int8]], int8]:
            return small

        def wide() -> Callable[[list[int64]], int64]:
            return large

        def main() -> str:
            gc_set_threshold(1)
            return repr((int(narrow()([int8(100), int8(40)])),
                         int(wide()([int64(2**60), int64(7)]))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("item_type", "diagnostic"), [
    ("str", "Function returns Callable"),
    ("int8", "incompatible nested representation"),
])
def test_callable_iterable_contracts_reject_incompatible_items(item_type, diagnostic):
    with pytest.raises(CompilationError, match=diagnostic):
        transpile_llvm(f'''
            from collections.abc import Callable, Iterable
            from pyjs import int8

            def consume(values: Iterable[int]) -> int:
                return sum(values)

            def factory() -> Callable[[list[{item_type}]], int]:
                return consume

            def main() -> int:
                factory()
                return 0
        ''')


def test_callable_iterable_contract_rejects_non_iterable_inputs():
    with pytest.raises(CompilationError, match="Function returns Callable"):
        transpile_llvm('''
            from collections.abc import Callable, Iterable

            def consume(values: Iterable[int]) -> int:
                return sum(values)

            def factory() -> Callable[[int], int]:
                return consume

            def main() -> int:
                factory()
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_iterable_allocation_failure_precedes_callback_entry(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Callable, Iterable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def consume(values: Iterable[int], events: list[int]) -> int:
            events.append(1)
            gc_collect()
            return sum(values)

        def factory() -> Callable[[list[int], list[int]], int]:
            return consume

        def producer(values: list[int]) -> Callable[[], Iterable[int]]:
            return lambda: values

        def main() -> int:
            callback = factory()
            values = [3, 4]
            events: list[int] = []
            result = -1
            caught = False
            arm(1)
            try:
                result = callback(values, events)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught or result != -1 or events:
                return 1
            if callback(values, events) != 7 or events != [1]:
                return 2
            source = producer(values)
            previous: Iterable[int] = values
            current = previous
            caught = False
            arm(1)
            try:
                current = source()
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught or current is not previous:
                return 3
            if sum(source()) != 7:
                return 4
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("optional", [False, True])
def test_callable_iterable_adapter_recovers_at_every_allocation(tmp_path, optimize, optional):
    annotation = "Iterable[int] | None" if optional else "Iterable[int]"
    source = transpile_llvm(f'''
        from collections.abc import Callable, Iterable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining
        def consume(values: {annotation}) -> int:
            if values is None:
                return -1
            result = 0
            for value in values:
                result += value
            return result
        def main() -> int:
            values = [3, 4]
            action: Callable[[{annotation}], int] = consume
            arm(1000)
            {"assert action(None) == -1 and remaining() == 1000" if optional else "pass"}
            result = action(values)
            stages = 1000 - remaining()
            arm(0)
            assert result == 7 and 0 < stages < 1000
            for failure in range(1, stages + 1):
                result = -1
                caught = False
                arm(failure)
                try:
                    result = action(values)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                assert caught and result == -1
                assert action(values) == 7 and values == [3, 4]
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""
