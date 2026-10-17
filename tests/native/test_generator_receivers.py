import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, sent", [
    ("int64", "int64(9007199254740993)"),
    ("list[str]", '["retained"]'),
])
@pytest.mark.parametrize("target", ["field", "property", "index", "chained"])
def test_receiving_targets_are_evaluated_after_resume_and_keep_input(optimize, annotation, sent, target):
    receiver = {
        "field": "select(boxes, events).value",
        "property": "select(boxes, events).exposed",
        "index": "select(boxes, events).items[index(events)]",
        "chained": ("select(boxes, events).value = select(boxes, events).exposed = "
                    "select(boxes, events).items[index(events)]"),
    }[target]
    LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs import int64
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, events: list[str]):
                self.value: {annotation} | None = None
                self.items: list[{annotation} | None] = [None]
                self.events = events
            @property
            def exposed(self) -> {annotation} | None:
                return self.value
            @exposed.setter
            def exposed(self, value: {annotation} | None) -> None:
                gc_collect()
                self.events.append("setter")
                self.value = value

        def select(boxes: list[Box], events: list[str]) -> Box:
            gc_collect()
            events.append("receiver")
            return boxes[0]

        def index(events: list[str]) -> int:
            gc_collect()
            events.append("index")
            return 0

        def values(boxes: list[Box], events: list[str]) -> Generator[str, {annotation}, None]:
            {receiver} = yield "ready"
            gc_collect()
            yield "done"

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            original = Box(events)
            replacement = Box(events)
            boxes = [original]
            source = values(boxes, events)
            assert next(source) == "ready"
            assert events == []
            boxes[0] = replacement
            assert source.send({sent}) == "done"
            assert original.value is None
            assert original.items[0] is None
            source.close()
            result = repr((replacement.value, replacement.items, events))
            events.clear()
            source = values(boxes, events)
            next(source)
            assert next(source) == "done"
            source.close()
            return result + repr((replacement.value, replacement.items, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_injection_skips_target_and_receiver_failure_uses_suspended_handler(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def target(events: list[str], fail: bool) -> list[int | None]:
            events.append("target")
            gc_collect()
            if fail:
                raise ValueError("target failed")
            return [None]

        def values(events: list[str], fail: bool) -> Generator[int, int, None]:
            try:
                target(events, fail)[0] = yield 1
            except ValueError as error:
                events.append(str(error))
                yield 2
            finally:
                events.append("cleanup")

        def main() -> str:
            events: list[str] = []
            source = values(events, True)
            assert next(source) == 1
            assert source.send(4) == 2
            source.close()
            assert events == ["target", "target failed", "cleanup"]
            events.clear()
            source = values(events, False)
            assert next(source) == 1
            assert source.throw(ValueError("injected")) == 2
            source.close()
            assert events == ["injected", "cleanup"]
            events.clear()
            source = values(events, False)
            assert next(source) == 1
            source.close()
            assert events == ["cleanup"]
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_receiver_evaluates_bounds_after_resume(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def bound(events: list[int], value: int) -> int:
            gc_collect()
            events.append(value)
            return value

        def values(items: list[str], events: list[int]) -> Generator[int, list[str], None]:
            items[bound(events, 1):bound(events, 2)] = yield 1
            yield 2

        def main() -> str:
            items = ["a", "b", "c"]
            events: list[int] = []
            source = values(items, events)
            assert next(source) == 1
            assert events == []
            items.append("d")
            assert source.send(["x", "y"]) == 2
            source.close()
            assert events == [1, 2]
            return repr(items)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
