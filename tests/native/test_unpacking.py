import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_loop_unpacking_preserves_nonempty_proof_and_once_only_source(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def row(events: list[int]) -> tuple[int, int]:
            events.append(1)
            gc_collect()
            return (2, 3)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            left: int | None = None
            for left, right in [row(events)]:
                pass
            total = left + right
            empty: list[tuple[int, int]] = []
            retained: int | None = None
            for retained, other in [*empty]:
                pass
            assert retained is None
            assert events == [1]
            return repr((total, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("statement, message", [
    ("left, right = (1,)", "cannot unpack 1 values into 2 targets"),
    ("*rest, = (int8(1), int64(2))", "List items"),
    ("left, right = range(2)", "native unpacking requires a statically typed tuple or list"),
])
def test_unpacking_unsupported_storage_boundaries_are_located(statement, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm(f"from pyjs import int8, int64\ndef main() -> int:\n    {statement}\n    return 0\n")
    assert caught.value.diagnostic.primary.span.start_position.line == 2


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_fixed_starred_remainder_uses_destination_type(optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int64
        from pyjs.native import gc_collect, gc_set_threshold

        class Holder:
            def __init__(self):
                self.items: list[int64] = [int64(1)]
            @property
            def value(self) -> list[int64]:
                return self.items
            @value.setter
            def value(self, items: list[int64]):
                gc_collect()
                self.items = items

        def owner(holder: Holder, events: list[int]) -> Holder:
            events.append(len(events))
            gc_collect()
            return holder

        def suspended(targets: list[list[int64]]) -> Generator[str, int, None]:
            first, *targets[(yield "index") or 0] = (9,)
            gc_collect()
            yield repr((first, targets))

        def parameter(rest: list[int64]) -> list[int64]:
            first, *rest = (1,)
            rest.append(int64(9007199254740993))
            return rest

        def main() -> str:
            gc_set_threshold(1)
            rest: list[int] = [4]
            first, *rest = (1,)
            rest.append(2)
            first, *[*rest] = (3,)
            rest.append(4)
            deep: list[int64] = [int64(5)]
            *[*[*deep]], = ()
            deep.append(int64(9007199254740993))
            holder = Holder()
            events: list[int] = []
            *owner(holder, events).items, = ()
            holder.items.append(int64(9007199254740993))
            field = repr(holder.items)
            first, *owner(holder, events).value = (3,)
            holder.items.append(int64(9007199254740995))
            containers: list[list[int64]] = [[int64(2)]]
            *containers[0], = ()
            containers[0].append(int64(9007199254740997))
            before = repr(containers)
            source = suspended(containers)
            assert next(source) == "index"
            assert repr(containers) == before
            gc_collect()
            resumed = source.send(0)
            source.close()
            containers[0].append(int64(9007199254740999))
            nested: object = 7
            try:
                *(nested,), = ()
            except ValueError:
                assert isinstance(nested, int)
                assert nested == 7
                events.append(7)
            gc_collect()
            return repr((first, rest, deep, field, holder.items, containers, resumed, events, parameter([])))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_exact_starred_and_nested_unpacking(optimize):
    LLVM().assert_matches_python('''
        from pyjs import StaticArray, int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def dynamic(values: tuple[int64, ...]) -> str:
            first, *middle, last = values
            return repr((first, middle, last))

        def shadowed() -> str:
            len = 99
            ValueError = 0
            try:
                left, right = list(range(1))
                return str(left + right + len + ValueError)
            except Exception as error:
                return str(error)

        def main() -> str:
            gc_set_threshold(1)
            errors: list[str] = []
            for size in range(5):
                items = list(range(size))
                try:
                    left, right = items
                    errors.append(str(left + right))
                except ValueError as error:
                    errors.append(str(error))
                try:
                    first, *middle, last = items
                    errors.append(repr((first, middle, last)))
                except ValueError as error:
                    errors.append(str(error))
            a, b = (int8(127), int64(9007199254740993))
            (c, d), (e, f) = [[1, 2], [3, 4]]
            number, *labels, final = (19, "label", 0.5, 31)
            *empty, = ()
            fixed: StaticArray[int8, 3] = [int8(126), int8(127), int8(1)]
            head, *tail = fixed
            gc_collect()
            return repr((errors, a + int8(1), b + int64(1), c + d + e + f,
                         number, labels, final, empty, head + tail[0], tail)) + dynamic((int64(2), int64(3), int64(4))) + shadowed()
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_unpack_stores_snapshot_one_level_and_preserve_partial_updates(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Panel:
            def __init__(self):
                self.left = -1
                self.right = -1
            @property
            def value(self) -> int:
                return self.right
            @value.setter
            def value(self, value: int):
                gc_collect()
                self.right = value

        def owner(panel: Panel, values: list[int], events: list[int], fail: bool) -> Panel:
            events.append(len(events) + 1)
            values[-1] = 99
            gc_collect()
            if fail and len(events) == 2:
                raise ValueError("target failed")
            return panel

        def main() -> str:
            result: list[str] = []
            for size in [1, 2, 3]:
                for fail in [False, True]:
                    values = list(range(size))
                    events: list[int] = []
                    panel = Panel()
                    message = "ok"
                    try:
                        owner(panel, values, events, fail).left, owner(panel, values, events, fail).value = values
                    except ValueError as error:
                        message = str(error)
                    result.append(repr((panel.left, panel.right, events, message)))
            nested = [2]
            events: list[int] = []
            panel = Panel()
            owner(panel, nested, events, False).left, (panel.value,) = (1, nested)
            result.append(repr((panel.left, panel.right, events)))
            target = [0]
            target[0], local = [4, 5]
            result.append(repr((target, local)))
            return repr(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_unpacking_receives_widths_none_errors_and_cleanup(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def fixed(events: list[str]) -> Generator[str, tuple[int8, int64], None]:
            try:
                left, right = yield "fixed"
                gc_collect()
                yield repr((left + int8(1), right + int64(1)))
            except TypeError as error:
                yield str(error)
            finally:
                events.append("fixed cleanup")

        def dynamic(events: list[str]) -> Generator[str, list[str], None]:
            try:
                first, *middle, last = yield "dynamic"
                gc_collect()
                yield repr((first, middle, last))
            except ValueError as error:
                yield str(error)
            finally:
                events.append("dynamic cleanup")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = fixed(events)
            assert next(source) == "fixed"
            result = source.send((int8(127), int64(9007199254740993)))
            source.close()
            absent = fixed(events)
            next(absent)
            result += next(absent)
            absent.close()
            for items in [["a" * 40], ["a" * 40, "b" * 40, "c" * 40]]:
                other = dynamic(events)
                assert next(other) == "dynamic"
                result += other.send(items)
                items.clear()
                gc_collect()
                other.close()
            return result + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_unpack_target_suspension_retains_snapshots_after_source_is_cleared(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, text: str):
                self.text = text

        def values(items: list[Box], targets: list[Box], events: list[str]) -> Generator[str, int, None]:
            left = Box("initial")
            try:
                left, targets[((yield "index") or 0)] = items
                yield left.text + targets[0].text
            except ValueError:
                yield left.text + targets[0].text
            finally:
                events.append(left.text)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            result = ""
            for action in [0, 1, 2]:
                items = [Box("first" * 40), Box("second" * 40)]
                targets = [Box("old")]
                source = values(items, targets, events)
                assert next(source) == "index"
                items.clear()
                gc_collect()
                if action == 0:
                    result += source.send(0)
                elif action == 1:
                    result += source.throw(ValueError("injected"))
                source.close()
            return result + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("items, expected_rest, count", [
    ('["first" * 40, "middle" * 40, "last" * 40]', '[items[1]]', 3),
    ('("first" * 40, "last" * 40)', '[]', 2),
])
def test_rest_allocation_failure_precedes_every_target_store(tmp_path, optimize, items, expected_rest, count):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def main() -> int:
            items = {items}
            stages = 1
            failure = 0
            while failure <= stages:
                first = "unchanged"
                rest = ["unchanged"]
                last = "unchanged"
                caught = False
                arm(1000 if failure == 0 else failure)
                try:
                    first, *rest, last = items
                except MemoryError:
                    caught = True
                if failure == 0:
                    stages = 1000 - remaining()
                arm(0)
                gc_collect()
                assert stages > 0
                assert caught == (failure != 0)
                if caught:
                    assert first == last == "unchanged" and rest == ["unchanged"]
                else:
                    assert first == items[0] and rest == {expected_rest} and last == items[-1]
                assert len(items) == {count}
                failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_empty_rest_failure_preserves_each_levels_store_order(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def main() -> int:
            items = (7,)
            stages = 1
            failure = 0
            early = False
            late = False
            while failure <= stages:
                first = -1
                rest: list[int] = [9]
                caught = False
                arm(1000 if failure == 0 else failure)
                try:
                    first, *[*rest] = items
                except MemoryError:
                    caught = True
                if failure == 0:
                    stages = 1000 - remaining()
                arm(0)
                gc_collect()
                assert caught == (failure != 0)
                if caught:
                    assert rest == [9]
                    if first == -1:
                        early = True
                    else:
                        assert first == 7
                        late = True
                else:
                    assert first == 7 and rest == []
                failure += 1
            assert early and late
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_tee_tuple_unpacking_checks_length_and_keeps_iterator_payloads(optimize):
    LLVM().assert_matches_python('''
        from itertools import tee
        from pyjs.native import gc_collect, gc_set_threshold

        def consume(count: int) -> str:
            try:
                left, right = tee(range(4), count)
                gc_collect()
                first = next(left)
                gc_collect()
                return repr((first, list(right), list(left)))
            except ValueError as error:
                return str(error)

        def main() -> str:
            gc_set_threshold(1)
            return consume(1) + consume(2) + consume(3)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_variadic_tuple_loop_and_comprehension_unpacking_checks_before_effects(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import combinations
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def source(width: int, events: list[str]) -> Iterator[tuple[str, ...]]:
            events.append("acquire")
            for row in combinations(["a", "b", "c"], width):
                events.append("row")
                gc_collect()
                yield row

        def checked(left: str, right: str, events: list[str]) -> bool:
            events.append(left + right)
            gc_collect()
            return True

        def main() -> str:
            gc_set_threshold(1)
            observations: list[str] = []
            for width in [1, 2, 3]:
                events: list[str] = []
                left = "unchanged"
                right = "unchanged"
                try:
                    for left, right in source(width, events):
                        events.append(left + right)
                    else:
                        events.append("exhausted")
                except ValueError as error:
                    observations.append(str(error))
                    assert left == right == "unchanged"
                observations.append(repr(events))
                events.clear()
                try:
                    observations.append(repr([left + right for left, right in source(width, events)
                                              if checked(left, right, events)]))
                except ValueError as error:
                    observations.append(str(error))
                    assert events == ["acquire", "row"]
                events.clear()
                deferred = (left + right for left, right in source(width, events))
                assert events == []
                try:
                    observations.append(repr(list(deferred)))
                except ValueError as error:
                    observations.append(str(error))
                    assert events == ["acquire", "row"]
            small = combinations([int8(127), int8(1)], 2)
            for left_small, right_small in small:
                assert left_small + right_small == int8(-128)
            return repr(observations)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
