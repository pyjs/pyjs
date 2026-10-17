import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_and_lone_star_consumption_straddle_suspension_differently(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def accept(*items: int, extra: int | None) -> str:
            return repr((items, extra))

        def values(items: list[int]) -> Generator[str, int, None]:
            yield accept(0, *items, extra=(yield "mixed"))
            yield accept(*items, extra=(yield "lone"))

        def main() -> str:
            items = [1]
            source = values(items)
            assert next(source) == "mixed"
            items.append(2)
            gc_collect()
            result = source.send(9)
            assert next(source) == "lone"
            items.append(3)
            result += source.send(8)
            source.close()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_keyword_snapshots_keep_values_and_independent_numeric_representations(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def fixed(small: int8, large: int64, label: str | None) -> str:
            gc_collect()
            return repr((small, large, label))

        def collect(**named: int64) -> str:
            gc_collect()
            return repr(named)

        def values(mapping: dict[str, int64]) -> Generator[str, str, None]:
            yield fixed(**{"small": int8(130)}, large=int64(9007199254740993), label=(yield "fixed"))
            yield collect(**mapping, last=int64(len((yield "mapping") or "")))

        def main() -> str:
            gc_set_threshold(1)
            mapping = {"saved": int64(9007199254740993)}
            source = values(mapping)
            assert next(source) == "fixed"
            result = source.send("label")
            assert next(source) == "mapping"
            mapping["saved"] = int64(0)
            mapping["later"] = int64(1)
            gc_collect()
            result += source.send("abc")
            source.close()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_duplicate_keywords_stop_before_later_suspension_or_star_consumption(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterator
        from pyjs.native import gc_collect

        def accept(*items: int, **named: int) -> str:
            return repr((items, named))

        def mark(events: list[str], value: int) -> int:
            gc_collect()
            events.append(str(value))
            return value

        def values(mapping: dict[str, int], items: Iterator[int], events: list[str]) -> Generator[str, int, None]:
            try:
                yield accept(*items, **mapping, **mapping, later=((yield "never") or 0))
            except TypeError:
                yield "duplicate"
            try:
                yield accept(**mapping, a=mark(events, 2), b=((yield "group") or 0), c=mark(events, 3))
            except TypeError:
                yield "group duplicate"

        def main() -> str:
            events: list[str] = []
            items = iter([1, 2])
            source = values({"a": 1}, items, events)
            assert next(source) == "duplicate"
            assert next(items) == 1
            assert next(source) == "group"
            assert events == ["2"]
            assert source.send(9) == "group duplicate"
            assert events == ["2", "3"]
            source.close()
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_collection_expansions_snapshot_sources_and_keep_tuple_representations(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import float32, int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def values(items: list[int64], mapping: dict[str, int64]) -> Generator[str, int64, None]:
            yield repr([*items, ((yield "list") or int64(0)), *items])
            yield repr((*items, ((yield "tuple") or int64(0)), *items))
            fixed = (int8(130), "text", float32(0.5), int64(9007199254740993))
            yield repr((*fixed, ((yield "fixed") or int64(0))))
            yield repr(sorted({*items, ((yield "set") or int64(0)), *items}))
            yield repr({**mapping, "sent": ((yield "dict") or int64(0)), **mapping})

        def main() -> str:
            gc_set_threshold(1)
            items = [int64(9007199254740993)]
            mapping = {"saved": int64(9007199254740993)}
            source = values(items, mapping)
            result = ""
            for stage in ["list", "tuple", "fixed", "set", "dict"]:
                assert next(source) == stage
                items.append(int64(len(items)))
                mapping["saved"] = int64(len(items))
                gc_collect()
                result += source.send(int64(130)) + ";"
            source.close()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_keyword_duplicates_keep_last_value_after_all_values_evaluate(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def mark(events: list[int], value: int) -> int:
            events.append(value)
            gc_collect()
            return value

        def accept(**named: int | None) -> str:
            return repr(named)

        def values(events: list[int]) -> Generator[str, int, None]:
            yield accept(**{"a": mark(events, 1), "a": (yield "pause"), "b": mark(events, 2)},
                         c=mark(events, 3))

        def main() -> str:
            events: list[int] = []
            source = values(events)
            assert next(source) == "pause"
            assert events == [1]
            result = source.send(9)
            assert events == [1, 2, 3]
            source.close()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_expansion_groups_keep_hash_and_comparison_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, events: list[str]):
                self.value = value
                self.events = events
            def __hash__(self) -> int:
                self.events.append("hash" + str(self.value))
                gc_collect()
                return 1
            def __eq__(self, other: Key) -> bool:
                self.events.append(str(self.value) + "=" + str(other.value))
                gc_collect()
                return self.value == other.value

        def key(value: int, events: list[str]) -> Key:
            events.append("key" + str(value))
            return Key(value, events)
        def mark(value: int, events: list[str]) -> int:
            events.append("value" + str(value))
            return value
        def source(mapping: dict[Key, int], events: list[str]) -> Generator[str, int, None]:
            result = {**mapping, key(1, events): (yield "ready"),
                      key(2, events): mark(2, events), **mapping}
            yield repr([(item.value, value) for item, value in result.items()])
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            mapping = {Key(0, events): 0}
            events.clear()
            iterator = source(mapping, events)
            result = [next(iterator), repr(events)]
            gc_collect()
            result.append(iterator.send(1))
            result.append(repr(events))
            iterator.close()
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind, count", [("set", 30), ("set", 31), ("dict", 15),
                                         ("dict", 16), ("dict", 17), ("dict", 18), ("dict", 34)])
def test_large_literal_hashing_boundaries_survive_suspension(optimize, kind, count):
    # These sizes straddle CPython's stack-construction groups; hash callbacks
    # must happen before/after the same suspension, not just produce equal keys.
    items = [f"Key({index}, events)" for index in range(count)]
    if kind == "set":
        items[-1] = f"Key(((yield 'pause') or {count - 1}), events)"
    else:
        items = [f"{key}: {index}" for index, key in enumerate(items)]
        items[-1] = f"Key({count - 1}, events): ((yield 'pause') or 0)"
    literal = "{" + ", ".join(items) + "}"
    LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        class Key:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events
            def __hash__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                return self.value
            def __eq__(self, other: "Key") -> bool:
                return self.value == other.value

        def values(events: list[int]) -> Generator[str, int, None]:
            result = {literal}
            yield str(len(result))

        def main() -> str:
            events: list[int] = []
            source = values(events)
            assert next(source) == "pause"
            before = repr(events)
            gc_collect()
            result = source.send({count - 1})
            source.close()
            return before + ";" + result + ";" + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansion_iteration_errors_throw_and_close_follow_cleanup(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterator
        from pyjs.native import gc_collect

        def items(events: list[str]) -> Iterator[str]:
            try:
                yield "first" * 40
                raise ValueError("iteration")
            finally:
                events.append("inner cleanup")

        def values(events: list[str], fail: bool) -> Generator[str, str, None]:
            try:
                try:
                    if fail:
                        result = [*items(events), ((yield "unreached") or "")]
                    else:
                        result = ["kept" * 40, *((yield "pause") or ""), "last"]
                    yield repr(result)
                except ValueError as error:
                    gc_collect()
                    yield str(error)
            finally:
                events.append("outer cleanup")

        def main() -> str:
            events: list[str] = []
            failed = values(events, True)
            assert next(failed) == "iteration"
            failed.close()
            thrown = values(events, False)
            assert next(thrown) == "pause"
            assert thrown.throw(ValueError("injected")) == "injected"
            thrown.close()
            closed = values(events, False)
            assert next(closed) == "pause"
            closed.close()
            gc_collect()
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_expansion_allocation_failures_do_not_skip_cleanup(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Generator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def values(events: list[int]) -> Generator[str, str, None]:
            yield "ready"
            try:
                try:
                    result = [*["kept" * 40], (yield "pause"), *["last" * 40]]
                    arm(0)
                    gc_collect()
                    assert len(result) == 3
                    yield "done"
                except MemoryError:
                    arm(0)
                    gc_collect()
                    yield "failed"
            finally:
                arm(0)
                events.append(1)

        def main() -> int:
            failures = 0
            successes = 0
            for budget in range(1, 65):
                events: list[int] = []
                source = values(events)
                assert next(source) == "ready"
                arm(budget)
                result = next(source)
                if result == "pause":
                    result = source.send(None)
                arm(0)
                if result == "failed":
                    failures += 1
                else:
                    assert result == "done"
                    successes += 1
                source.close()
                assert events == [1]
                gc_collect()
            assert failures > 0 and successes > 0
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
