import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import GENERATOR_CLEANUP_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_generator_cleanup_contract(optimize):
    result = LLVM().assert_matches_python(GENERATOR_CLEANUP_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, GENERATOR_CLEANUP_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_close_is_lazy_idempotent_and_runs_nested_cleanup(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Resource:
            def __init__(self, events: list[int]):
                self.events = events
            def __enter__(self) -> int:
                self.events.append(1)
                return 7
            def __exit__(self, kind: object, error: object, trace: object) -> bool:
                gc_collect()
                assert kind is GeneratorExit
                self.events.append(4)
                return False

        def values(events: list[int]) -> Generator[int8, None, None]:
            with Resource(events) as value:
                try:
                    events.append(2)
                    yield int8(value)
                finally:
                    gc_collect()
                    events.append(3)

        def inferred(events: list[int]):
            try:
                yield 1
            finally:
                events.append(5)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            untouched = values(events)
            assert untouched.close() is None
            assert next(untouched, None) is None
            untouched.close()
            assert events == []
            source = values(events)
            assert next(source) == int8(7)
            source.close()
            source.close()
            assert next(source, None) is None
            other = inferred(events)
            assert next(other) == 1
            other.close()
            expression = (value for value in range(3))
            assert expression.__iter__() is expression
            assert next(expression) == 0
            assert expression.close() is None
            assert next(expression, -1) == -1
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("close_retry", [False, True], ids=["resume", "close-again"])
def test_close_distinguishes_baseexception_and_keeps_a_yielding_generator_resumable(optimize, close_retry):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def handled(events: list[int]):
            try:
                yield 1
            except Exception:
                events.append(99)
            except BaseException:
                events.append(2)
            finally:
                gc_collect()
                events.append(3)

        def stubborn(events: list[int]):
            try:
                yield 1
            except GeneratorExit:
                events.append(4)
                yield 2
                events.append(5)
            finally:
                events.append(6)

        def failed(events: list[int]):
            try:
                yield 1
            finally:
                events.append(7)
                raise ValueError("cleanup failed")

        def main() -> str:
            events: list[int] = []
            first = handled(events)
            next(first)
            first.close()
            second = stubborn(events)
            next(second)
            try:
                second.close()
                assert False
            except RuntimeError as error:
                assert str(error) == "generator ignored GeneratorExit"
            if CLOSE_RETRY:
                assert second.close() is None
            else:
                assert next(second, -1) == -1
            second.close()
            third = failed(events)
            next(third)
            try:
                third.close()
                assert False
            except ValueError as error:
                assert str(error) == "cleanup failed"
            third.close()
            assert next(third, -1) == -1
            assert events == EXPECTED_EVENTS
            return repr(events)
    '''.replace("CLOSE_RETRY", str(close_retry)).replace(
        "EXPECTED_EVENTS", "[2, 3, 4, 6, 7]" if close_retry else "[2, 3, 4, 5, 6, 7]",
    ), optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_close_reentry_does_not_inject_into_or_close_the_running_frame(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def values(holders: list[Generator[int, None, None]]) -> Generator[int, None, None]:
            try:
                holders[0].close()
                assert False
            except ValueError as error:
                assert str(error) == "generator already executing"
            yield 7
            gc_collect()
            yield 9

        def main() -> str:
            holders: list[Generator[int, None, None]] = []
            cursor = values(holders)
            holders.append(cursor)
            assert next(cursor) == 7
            assert next(cursor) == 9
            cursor.close()
            assert next(cursor, -1) == -1
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_yield_boxing_failure_runs_cleanup_and_exhausts_the_generator(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Generator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def values(events: list[int]) -> Generator[object, None, None]:
            payload = "payload" + str(9)
            try:
                arm(1)
                yield payload
            finally:
                arm(0)
                gc_collect()
                events.append(1)

        def main() -> int:
            events: list[int] = []
            source = values(events)
            saved: object = "unchanged"
            value = saved
            try:
                value = next(source)
            except MemoryError:
                assert value is saved
                assert next(source, None) is None
                source.close()
                assert events == [1]
                return 0
            return 1
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_allocation_failure_in_close_cleanup_exhausts_the_source(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def values(events: list[int], size: int):
            try:
                yield 1
            finally:
                # Fail the cleanup allocation, not best-effort construction
                # of the injected GeneratorExit's suspension traceback.
                arm(1)
                events.append(len("x" * size))

        def main() -> int:
            events: list[int] = []
            value = values(events, 4096)
            next(value)
            caught = False
            try:
                value.close()
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught:
                return 1
            if events:
                return 2
            if next(value, None) is not None:
                return 3
            value.close()
            return 0 if not events else 4
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("module", ["typing", "collections.abc"])
def test_generator_interface_erasure_retains_identity_and_represented_items(module):
    LLVM().assert_matches_python(f'''
        from {module} import Generator as Stream, Iterator
        from pyjs import int8
        from pyjs.native import gc_collect

        def values(events: list[int]) -> Stream[int8, None, None]:
            try:
                yield int8(127)
                yield int8(-128)
            finally:
                events.append(1)

        def take(cursor: Iterator[int8]) -> int8:
            gc_collect()
            return next(cursor)

        def main() -> str:
            events: list[int] = []
            source = values(events)
            erased: Iterator[int8] = source
            assert source is erased
            assert take(erased) == int8(127)
            source.close()
            assert next(erased, None) is None
            assert events == [1]
            return "passed"
    ''', optimize=2, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("expression, message", [
    ("cast(Generator[int, None, None], iter([1]))", "Generator views require a Generator source"),
    ("cast(Iterator[int], (value for value in [True]))", "iterator views require an explicit numeric conversion"),
    ("cast(Generator[int, str, None], (value for value in [1]))", "iterator views require covariant yields/results and contravariant sends"),
])
def test_generator_views_do_not_reinterpret_incompatible_state_or_payloads(expression, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            from collections.abc import Generator, Iterator
            from typing import cast
            def main() -> int:
                cursor = {expression}
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_handler_snapshots_and_pending_reraises_survive_suspension(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def values(label: str, events: list[str]) -> Iterator[str]:
            try:
                try:
                    raise ValueError(label + ":original")
                except ValueError as error:
                    yield "caught"
                    gc_collect()
                    yield str(error)
                    try:
                        raise TypeError(label + ":nested")
                    except TypeError as nested:
                        yield str(nested)
                        gc_collect()
                        assert str(nested) == label + ":nested"
                    assert str(error) == label + ":original"
                    raise
            finally:
                events.append(label + ":finally")
                yield "cleanup"
                gc_collect()
                events.append(label + ":done")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            first = values("first", events)
            second = values("second", events)
            assert next(first) == "caught"
            assert next(second) == "caught"
            gc_collect()
            assert next(first) == "first:original"
            assert next(second) == "second:original"
            assert next(first) == "first:nested"
            assert next(second) == "second:nested"
            assert next(first) == "cleanup"
            assert next(second) == "cleanup"
            assert events == ["first:finally", "second:finally"]
            try:
                next(first)
                assert False
            except ValueError as first_error:
                assert str(first_error) == "first:original"
            try:
                next(second)
                assert False
            except ValueError as second_error:
                assert str(second_error) == "second:original"
            assert next(first, "end") == "end"
            assert next(second, "end") == "end"
            return "|".join(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_context_manager_cleanup_on_normal_return_suppression_and_failure(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Scope:
            def __init__(self, events: list[str], fail_exit: bool):
                self.events = events
                self.fail_exit = fail_exit

            def __enter__(self) -> str:
                self.events.append("enter")
                return "body"

            def __exit__(self, kind: type[BaseException] | None,
                         value: BaseException | None, traceback: object) -> bool:
                gc_collect()
                if value is None:
                    assert kind is None and traceback is None
                    self.events.append("normal")
                else:
                    self.events.append(str(value))
                if self.fail_exit:
                    raise RuntimeError("exit failed")
                return True

        def values(events: list[str], mode: int) -> Iterator[str]:
            try:
                with Scope(events, mode == 3) as label:
                    yield label
                    gc_collect()
                    if mode == 1:
                        return
                    if mode >= 2:
                        raise ValueError("suppressed")
                    yield "second"
                yield "outside"
            finally:
                events.append("finally")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            for mode in range(4):
                cursor = values(events, mode)
                assert next(cursor) == "body"
                assert events[-1] == "enter"
                gc_collect()
                if mode == 3:
                    try:
                        next(cursor)
                        assert False
                    except RuntimeError as error:
                        assert str(error) == "exit failed"
                    assert next(cursor, "end") == "end"
                else:
                    tail = list(cursor)
                    if mode == 0:
                        assert tail == ["second", "outside"]
                    elif mode == 1:
                        assert tail == []
                    else:
                        assert tail == ["outside"]
            return "|".join(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_loop_exits_resume_cleanup_and_handler_failures_exhaust(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect

        def values(events: list[int]) -> Iterator[int]:
            for value in range(4):
                try:
                    if value == 1:
                        continue
                    if value == 2:
                        break
                    yield value
                finally:
                    yield value + 10
                    gc_collect()
                    events.append(value)
            else:
                events.append(99)
            try:
                raise ValueError("caught")
            except ValueError as error:
                yield len(str(error))
                gc_collect()
                raise TypeError(str(error) + ":replaced")
            finally:
                events.append(100)

        def main() -> str:
            events: list[int] = []
            cursor = values(events)
            yielded: list[int] = []
            try:
                for value in cursor:
                    yielded.append(value)
                    gc_collect()
                assert False
            except TypeError as error:
                assert str(error) == "caught:replaced"
            assert yielded == [0, 10, 11, 12, 6]
            assert events == [0, 1, 2, 100]
            assert next(cursor, -1) == -1
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))
