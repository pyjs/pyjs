import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("value_type", ["int", "int8"])
@pytest.mark.parametrize("statement, order", [
    ("target(items, events)[index(events)] = yield ready(events)", [1, 2, 3]),
    ("target(items, events).__setitem__(index(events), (yield ready(events)))", [2, 3, 1]),
])
def test_yielded_item_assignment_selects_overload_before_destination_conversion(optimize, value_type, statement, order):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def ready(events: list[int]) -> str:
            events.append(1)
            gc_collect()
            return 'ready'
        def target(items: list[{value_type} | None], events: list[int]) -> list[{value_type} | None]:
            events.append(2)
            gc_collect()
            return items
        def index(events: list[int]) -> int:
            events.append(3)
            gc_collect()
            return 0
        def values(items: list[{value_type} | None], events: list[int]) -> Generator[str, {value_type}, None]:
            {statement}
            gc_collect()
            yield repr(items[0])
        def main() -> str:
            gc_set_threshold(1)
            for sending in [False, True]:
                events: list[int] = []
                items: list[{value_type} | None] = [None]
                source = values(items, events)
                assert next(source) == 'ready'
                result = source.send({value_type}(7)) if sending else next(source)
                assert result == ('7' if sending else 'None')
                assert events == {order!r}
                assert next(source, None) is None
            return 'passed'
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("destination, message", [
    ("object", "cannot erase represented scalar arithmetic"),
    ("int | None", "Stored value uses an incompatible representation"),
    ("int16 | None", "different fixed-width numeric types cannot be assigned implicitly"),
])
def test_receive_normalization_rejects_portable_scalar_erasure_or_width_change(destination, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm(f'''
            from collections.abc import Generator
            from pyjs import int8, int16
            def values() -> Generator[int, int8, None]:
                result: {destination} = yield 1
                yield 2
            def main() -> int:
                return next(values())
        ''')
    assert caught.value.diagnostic.primary.span.start_position.line == 4


@pytest.mark.parametrize("annotation", ["str | None", "int | None", "int64 | None"])
@pytest.mark.parametrize("first", ["first = yield 'first'", "first = ((yield 'first'),)"])
def test_later_send_inference_cannot_reinterpret_an_earlier_receive(annotation, first):
    with pytest.raises(CompilationError, match="input type must be known before") as caught:
        transpile_llvm(f'''
            from pyjs import int64
            def values():
                {first}
                later: {annotation} = yield "later"
                yield repr(later)
            def main() -> str:
                return next(values())
        ''')
    assert caught.value.diagnostic.primary.span.start_position.line == 3
    assert caught.value.diagnostic.help == (
        "Declare Generator[YieldType, SendType, ReturnType] on the function "
        "or annotate its first receiving assignment.",
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_declared_inputs_and_discarded_priming_yields_keep_source_order(optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int64
        from pyjs.native import gc_collect, gc_set_threshold

        def declared() -> Generator[str, str | None, None]:
            first = yield "first"
            later: str | None = yield repr(first)
            gc_collect()
            yield repr(later)

        def inferred():
            yield "discarded"
            first: int64 | None = yield "ready"
            later = yield repr(first)
            gc_collect()
            yield repr(later)

        def main() -> str:
            gc_set_threshold(1)
            source = declared()
            result = [next(source), source.send("seven"), source.send("nine")]
            source.close()
            numeric = inferred()
            result.append(next(numeric))
            result.append(numeric.send(int64(10)))
            result.append(numeric.send(int64(9007199254740993)))
            result.append(numeric.send(int64(9007199254740995)))
            numeric.close()
            return repr(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, argument, expected", [
    ("int", "7", "7"),
    ("int8", "int8(130)", "-126"),
    ("int64", "int64(9007199254740993)", "9007199254740993"),
    ("float32", "float32(1.25)", "1.25"),
    ("bool", "False", "False"),
    ("list[str]", "['kept']", "['kept']"),
    ("list[int8]", "[int8(130)]", "[-126]"),
    ("int | str", "'word'", "'word'"),
    ("int | str", "0", "0"),
])
def test_send_and_next_keep_wire_representation_and_do_not_replay_inputs(optimize, annotation, argument, expected):
    LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def values() -> Generator[str, {annotation}, None]:
            received = yield "ready"
            gc_collect()
            yield repr(received)
            received = yield "again"
            gc_collect()
            yield repr(received)

        def main() -> str:
            gc_set_threshold(1)
            source = values()
            assert source.send(None) == "ready"
            assert source.send({argument}) == {expected!r}
            assert next(source) == "again"
            assert next(source) == "None"
            source.close()
            try:
                source.send({argument})
                assert False
            except StopIteration:
                pass
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_fresh_send_and_reentry_fail_without_consuming_or_corrupting_the_generator(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def argument(events: list[int]) -> int:
            events.append(1)
            gc_collect()
            return 7

        def values(holders: list[Generator[str, int, None]]) -> Generator[str, int, None]:
            try:
                holders[0].send(20)
                assert False
            except ValueError as error:
                assert str(error) == "generator already executing"
            value = yield "ready"
            gc_collect()
            yield repr(value)

        def main() -> str:
            holders: list[Generator[str, int, None]] = []
            events: list[int] = []
            source = values(holders)
            holders.append(source)
            try:
                source.send(argument(events))
                assert False
            except TypeError as error:
                assert str(error) == "can't send non-None value to a just-started generator"
            assert events == [1]
            assert source.send(None) == "ready"
            assert source.send(9) == "9"
            source.close()
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_wider_receiving_locals_do_not_change_input_storage(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def values() -> Generator[str, int, None]:
            first: object = yield "ready"
            gc_collect()
            second: int | None = yield repr(first)
            gc_collect()
            first = yield repr(second)
            gc_collect()
            yield repr(first)

        def inferred():
            value: int | None = yield "ready"
            gc_collect()
            yield repr(value)

        def main() -> str:
            for sending in [False, True]:
                source = values()
                assert next(source) == "ready"
                assert (source.send(0) if sending else next(source)) == ("0" if sending else "None")
                assert (source.send(7) if sending else next(source)) == ("7" if sending else "None")
                assert (source.send(9) if sending else next(source)) == ("9" if sending else "None")
                assert next(source, None) is None
            other = inferred()
            next(other)
            assert other.send(5) == "5"
            other.close()
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("receive", ["yield 1", "passthrough((yield 1))"], ids=["local", "argument"])
def test_receiving_box_allocation_failure_is_caught_at_the_suspended_yield(tmp_path, optimize, receive):
    source = transpile_llvm('''
        from collections.abc import Generator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def passthrough(value: object) -> object:
            return value

        def values(events: list[int]) -> Generator[int, int, None]:
            try:
                try:
                    received: object = RECEIVE
                except MemoryError:
                    arm(0)
                    gc_collect()
                    events.append(1)
                    received = yield 2
                gc_collect()
                assert repr(received) == "9"
                yield 3
            finally:
                arm(0)
                events.append(2)

        def main() -> int:
            events: list[int] = []
            source = values(events)
            assert next(source) == 1
            arm(1)
            assert source.send(7) == 2
            assert events == [1]
            assert source.send(9) == 3
            source.close()
            assert events == [1, 2]
            return 0
    '''.replace("RECEIVE", receive))
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_inputs_ignored_yields_and_erased_inputs(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def values() -> Generator[str, object, None]:
            yield "ready"
            gc_collect()
            received = yield "ignored"
            gc_collect()
            yield repr(received)

        def main() -> str:
            gc_set_threshold(1)
            source = values()
            missing: object = None
            assert source.send(missing) == "ready"
            assert source.send(['discarded']) == "ignored"
            assert next(source) == "None"
            source.close()
            source = values()
            assert source.send(None) == "ready"
            assert source.send(None) == "ignored"
            assert source.send(['kept']) == "['kept']"
            source.close()
            empty_input = (value for value in [1, 2])
            assert empty_input.send(None) == 1
            assert empty_input.send(None) == 2
            empty_input.close()
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_nonnullable_receiving_local_checks_next_inside_its_handler(tmp_path, optimize):
    # Python ignores the annotation, so this is a checked native boundary,
    # not a differential runtime contract.
    source = '''
        from collections.abc import Generator

        def values() -> Generator[int, int, None]:
            try:
                received: int = yield 1
                yield received
            except TypeError as error:
                assert str(error) == "generator received None for a nonnullable yield result"
                yield 3

        def main() -> int:
            source = values()
            assert next(source) == 1
            assert next(source) == 3
            source.close()
            source = values()
            assert next(source) == 1
            assert source.send(7) == 7
            source.close()
            return 0
    '''
    result = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("receiver", ["int64", "int64 | None"])
def test_portable_receiving_reassignment_preserves_wide_input_and_narrow_output(optimize, receiver):
    LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs import int8, int64
        from pyjs.native import gc_collect

        def values() -> Generator[int8, int64, None]:
            received: {receiver} = yield int8(1)
            gc_collect()
            if received is not None:
                assert received == int64(9007199254740993)
                received = yield int8(received)
                gc_collect()
                if received is not None:
                    assert received == int64(9007199254740995)
                    yield int8(received)

        def main() -> str:
            source = values()
            assert next(source) == int8(1)
            assert source.send(int64(9007199254740993)) == int8(1)
            assert source.send(int64(9007199254740995)) == int8(3)
            source.close()
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))
