import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_calls_freeze_earlier_operands_and_preserve_later_evaluation(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def mark(events: list[str], value: str) -> str:
            events.append(value)
            gc_collect()
            return value

        def combine(left: str, middle: str | None, *, right: str) -> str:
            gc_collect()
            return repr((left, middle, right))

        def values(items: list[str], events: list[str]) -> Generator[str, str, None]:
            yield combine(mark(events, items[0]), (yield "inner"), right=mark(events, items[1]))
            yield repr((mark(events, "tuple"), (yield "second")))

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            items = ["before", "later"]
            source = values(items, events)
            assert next(source) == "inner"
            assert events == ["before"]
            items[0] = "changed"
            items[1] = "after"
            result = source.send("input")
            assert events == ["before", "after"]
            assert next(source) == "second"
            result += next(source)
            source.close()
            return result + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_conditional_and_boolean_suspensions_are_lazy(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def values(flag: bool) -> Generator[str, str, None]:
            yield repr((yield "yes") if flag else (yield "no"))
            yield repr(flag and (yield "and"))
            yield repr(flag or (yield "or"))

        def main() -> str:
            result: list[str] = []
            for flag in [False, True]:
                source = values(flag)
                result.append(next(source))
                result.append(source.send("chosen"))
                result.append(next(source))
                gc_collect()
                if flag:
                    result.append(source.send("both"))
                    result.append(next(source))
                else:
                    result.append(next(source))
                    result.append(source.send("other"))
                source.close()
            return repr(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_injected_exception_skips_remaining_operands_and_runs_cleanup(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def mark(events: list[str], value: str) -> str:
            events.append(value)
            gc_collect()
            return value

        def values(events: list[str]) -> Generator[str, str, None]:
            try:
                yield repr([mark(events, "before"), (yield "inner"), mark(events, "after")])
            except ValueError as error:
                yield str(error)
            finally:
                events.append("cleanup")

        def main() -> str:
            events: list[str] = []
            source = values(events)
            assert next(source) == "inner"
            assert source.throw(ValueError("injected")) == "injected"
            source.close()
            assert events == ["before", "cleanup"]
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_chained_comparisons_and_membership_keep_source_order(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int64
        from pyjs.native import gc_collect

        def number(value: int64 | None) -> int64:
            if value is not None:
                return value
            raise ValueError("missing")

        def mark(events: list[str], value: int64) -> int64:
            events.append(str(value))
            gc_collect()
            return value

        def items(events: list[str]) -> list[int64]:
            events.append("items")
            return [int64(9007199254740993)]

        def values(events: list[str]) -> Generator[str, int64, None]:
            yield repr(mark(events, int64(0)) < number((yield "middle")) < mark(events, int64(10)))
            yield repr(number((yield "member")) in items(events))

        def main() -> str:
            result: list[str] = []
            events: list[str] = []
            for value in [int64(-1), int64(5)]:
                source = values(events)
                result.append(next(source))
                result.append(source.send(value))
                result.append(next(source))
                result.append(source.send(int64(9007199254740993)))
                source.close()
            assert events == ["0", "items", "0", "10", "items"]
            return repr(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_formatted_values_finish_before_later_suspension(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        class Value:
            def __init__(self, events: list[str]):
                self.events = events
            def __format__(self, spec: str) -> str:
                gc_collect()
                self.events.append(spec)
                return "formatted"

        def values(events: list[str]) -> Generator[str, str, None]:
            yield f"{Value(events):first}:{(yield 'middle')!r}:{Value(events):last}"

        def main() -> str:
            events: list[str] = []
            source = values(events)
            assert next(source) == "middle"
            assert events == ["first"]
            result = source.send("sent")
            assert events == ["first", "last"]
            source.close()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_comprehension_outer_source_suspends_without_running_its_lazy_body(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def received(value: list[int] | None) -> list[int]:
            if value is not None:
                return value
            raise ValueError("missing")

        def mark(events: list[int], value: int) -> int:
            events.append(value)
            gc_collect()
            return value

        def values(events: list[int]) -> Generator[str, list[int], None]:
            pending = (mark(events, value) for value in received((yield "source")))
            yield "created"
            yield repr(list(pending))
            yield repr([mark(events, value) for value in received((yield "eager"))])

        def main() -> str:
            events: list[int] = []
            source = values(events)
            assert next(source) == "source"
            assert source.send([1, 2]) == "created"
            assert events == []
            result = next(source)
            assert events == [1, 2]
            assert next(source) == "eager"
            result += source.send([3, 4])
            source.close()
            assert events == [1, 2, 3, 4]
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    'combine(*items, (yield "inner"))',
    'repr([*items, (yield "inner")])',
    'repr({**mapping, "sent": (yield "inner")})',
])
def test_suspending_expansions_match_python(expression, optimize):
    LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        def combine(*args: str | None) -> str:
            return repr(args)
        def values() -> Generator[str, str, None]:
            items: list[str | None] = ["prefix"]
            mapping: dict[str, str | None] = {{"prefix": "value"}}
            yield {expression}
        def main() -> str:
            source = values()
            assert next(source) == "inner"
            result = source.send("sent")
            source.close()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


def test_generator_lambda_has_a_focused_diagnostic():
    with pytest.raises(CompilationError, match="native generator lambdas require"):
        transpile_llvm('''
            def main() -> int:
                source = (lambda: (yield 1))()
                return next(source)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_suspending_conditions_collections_and_assertions_follow_control_flow(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def mark(events: list[str], value: str) -> str:
            events.append(value)
            gc_collect()
            return value

        def values(events: list[str]) -> Generator[str, str, None]:
            while (yield "condition"):
                yield repr({mark(events, "key"): (yield "dictionary")})
                yield str(len({mark(events, "member"), (yield "set")}))
            if (yield "if"):
                yield "true"
            assert True, (yield "never")
            try:
                assert False, (yield "message")
            except AssertionError as error:
                yield str(error)

        def main() -> str:
            events: list[str] = []
            source = values(events)
            result: list[str] = [next(source)]
            result.append(source.send("yes"))
            assert events == ["key"]
            result.append(source.send("value"))
            result.append(next(source))
            assert events == ["key", "member"]
            result.append(source.send("second"))
            result.append(next(source))
            result.append(next(source))
            result.append(source.send("yes"))
            result.append(next(source))
            result.append(source.send("assertion"))
            source.close()
            return repr(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_is_selected_before_argument_suspension(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable, Generator
        from pyjs.native import gc_collect

        def first(value: str | None) -> str:
            return "first:" + repr(value)
        def second(value: str | None) -> str:
            return "second:" + repr(value)

        def values(callbacks: list[Callable[[str | None], str]]) -> Generator[str, str, None]:
            yield callbacks[0]((yield "argument"))

        def main() -> str:
            callbacks: list[Callable[[str | None], str]] = [first]
            source = values(callbacks)
            assert next(source) == "argument"
            callbacks[0] = second
            gc_collect()
            result = source.send("sent")
            source.close()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_assignment_value_precedes_suspending_target(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def received(value: list[int] | None) -> list[int]:
            if value is not None:
                return value
            raise ValueError("missing")

        def values(items: list[int]) -> Generator[str, list[int], None]:
            received((yield "target"))[0] = items[0]
            yield "done"

        def main() -> str:
            items = [7]
            target = [0]
            source = values(items)
            assert next(source) == "target"
            items[0] = 99
            gc_collect()
            assert source.send(target) == "done"
            source.close()
            return repr(target)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_unaliased_earlier_operand_is_rooted_in_the_suspended_frame(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: list[str]):
                self.value = value

        def combine(left: Box, right: str | None) -> str:
            gc_collect()
            return left.value[0] + repr(right)

        def values(seed: int) -> Generator[str, str, None]:
            yield combine(Box(["kept" + str(seed)]), (yield "argument"))

        def main() -> str:
            gc_set_threshold(1)
            source = values(7)
            assert next(source) == "argument"
            gc_collect()
            result = source.send("sent")
            source.close()
            gc_collect()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))
