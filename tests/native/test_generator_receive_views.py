import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("receiving", [
    "received: Iterable[int] | None = yield -1; yield consume(received)",
    "yield consume((yield -1))",
])
def test_received_views_keep_virtual_acquisition_and_no_eager_iteration(tmp_path, optimize, receiving):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Generator, Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        class Rows:
            def __init__(self, events: list[int]):
                self.events = events
            def __iter__(self):
                self.events.append(1)
                yield 1
        class More(Rows):
            def __iter__(self):
                self.events.append(2)
                gc_collect()
                yield 2
                yield 3
        def consume(value: Iterable[int] | None) -> int:
            gc_collect()
            return -2 if value is None else sum(value) + sum(value)
        def values() -> Generator[int, Rows, None]:
            {receiving}
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            result: list[int] = []
            for send in [False, True]:
                source = values()
                result.append(next(source))
                assert events == []
                result.append(source.send(More(events)) if send else next(source))
                assert next(source, None) is None
            return repr((result, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reference_inputs_and_none_only_inputs_survive_wider_receivers(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        class Rows:
            def __init__(self, items: list[int]):
                self.items = items

            def __iter__(self):
                for item in self.items:
                    gc_collect()
                    yield item

        def protocols() -> Generator[str, Rows, None]:
            received: Iterable[int] | None = yield "ready"
            gc_collect()
            yield repr(list(received)) if received is not None else "none"

        def references() -> Generator[str, list[int], None]:
            received: object = yield "ready"
            gc_collect()
            yield repr(received)

        def empty() -> Generator[str, None, None]:
            received: object = yield "ready"
            gc_collect()
            yield repr(received)

        def objects() -> Generator[str, object, None]:
            received = yield "ready"
            gc_collect()
            yield repr(received)

        def main() -> str:
            gc_set_threshold(1)
            result: list[str] = []
            for send in [False, True]:
                source = references()
                next(source)
                result.append(source.send([1, 2]) if send else next(source))
                assert next(source, None) is None
                protocol_source = protocols()
                next(protocol_source)
                result.append(protocol_source.send(Rows([3, 4])) if send else next(protocol_source))
                assert next(protocol_source, None) is None
            empty_source = empty()
            result.append(empty_source.send(None))
            result.append(empty_source.send(None))
            object_source = objects()
            result.append(object_source.send(None))
            result.append(object_source.send(None))
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
