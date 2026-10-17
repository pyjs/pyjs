import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_common_union_fields_follow_each_layout_and_preserve_evaluation_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class First:
            def __init__(self, value: int):
                self.flag = True
                self.value = value
                self.label = "first"

        class Child(First):
            def __init__(self, value: int):
                super().__init__(value)
                self.extra = 99

        class Second:
            def __init__(self, value: int):
                self.label = "second"
                self.padding = 2.5
                self.value = value

        def target(value: First | Second, events: list[str]) -> First | Second:
            events.append("target")
            gc_collect()
            if value.value == 12:
                raise ValueError("target failed")
            return value

        def replacement(events: list[str], fail: bool) -> str:
            events.append("value")
            gc_collect()
            if fail:
                raise ValueError("value failed")
            return "updated" + str(len(events))

        def update(value: First | Second) -> str:
            events: list[str] = []
            value.value = value.value + 10
            error_message = "ok"
            try:
                target(value, events).label = replacement(events, value.value == 13)
            except ValueError as error:
                error_message = str(error)
                value.label = "recovered"
            gc_collect()
            return str((value.value, value.label, events, error_message))

        def main() -> str:
            gc_set_threshold(1)
            values: list[First | Second] = [First(1), Second(2), Child(3)]
            return "|".join([update(value) for value in values])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_field_writes_convert_each_validated_storage_layout(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int16
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        class First:
            def __init__(self):
                self.small = int8(1)
                self.payload = Box(1)
                self.items: list[Box] = []
                self.text: int8 | str = int8(7)

        class Second:
            def __init__(self):
                self.payload: Box | str = "second"
                self.items: list[Box] | None = None
                self.small: int8 | None = None
                self.text: int16 | str | None = int16(300)

        def owner(value: First | Second) -> First | Second:
            gc_collect()
            return value

        def update(value: First | Second, box: Box) -> str:
            owner(value).small = int8(127)
            owner(value).small: int8 = int8(-128)
            owner(value).payload = box
            owner(value).items = [box]
            owner(value).payload, owner(value).items = box, [box]
            owner(value).text = "updated" + str(box.value)
            gc_collect()
            small = value.small
            payload = value.payload
            items = value.items
            if small is None or items is None or not isinstance(payload, Box):
                raise RuntimeError("stored field lost its type")
            return str((int(small), payload.value, payload is box, items[0] is box, value.text))

        def main() -> str:
            gc_set_threshold(1)
            box = Box(99)
            return update(First(), box) + update(Second(), box)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
